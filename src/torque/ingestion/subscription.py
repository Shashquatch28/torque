"""Leg 3 — `subscription.charged.failed` ingestion (Blueprint §2.3 / §2.7 / Part A §3).

Mirrors the Leg-1 shape (`buffer.py` + `cases.py`) with the differences the
blueprint calls for:

* the self-recovery buffer is **30 s** (`PolicyConfig.subscription_failure_buffer_seconds`),
  not 90 s — background auto-debits have no live-checkout retry-UX pattern, but a
  race between a failure and a `subscription.charged` for the same billing
  attempt is still possible (§2.3);
* the interim-success event type is `subscription.charged`, matched on
  `subscription.entity.id`;
* the case is `SUBSCRIPTION_FAILURE` with a typed `SubscriptionFailureContext`
  (`mandate_id`, `mandate_type`, `billing_cycle`, `subscription_id`);
* rail-specific retry-budget seeding in the same transaction (§2.7 / Part A §3,
  D-069 / D-072): `UPI_AUTOPAY` → `UPIRetryBudget` (`attempts_used = 1` — the
  failed charge IS the original attempt); `NACH` → `NACHRetryPolicy`
  (`clearing_cycle_status = RETURNED`, `dishonour_count_this_fy = 1`); `CARD` →
  `CardRetryBudget` (reuses `cases.seed_card_retry_budget`). Per-decline
  increments and `mandate_cancelled_at` remain Module 5.

There is no cross-leg dedup for Leg 3 (§2.4 is Leg 1 ↔ Leg 2 only). Cases are
created in `DETECTED` and left there; the §2.7 systemic hold hook (M7c) still
applies. The Celery task wraps everything in one `session_scope()` transaction.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.config import get_policy
from torque.db.scoped import TenantScope
from torque.enums import CaseStatus, ClearingCycleStatus, LegType, MandateType
from torque.ingestion import payloads
from torque.ingestion.cases import seed_card_retry_budget
from torque.ingestion.identity import resolve_counterparty
from torque.ingestion.outcomes import BufferOutcome
from torque.ingestion.systemic import apply_active_hold_if_any
from torque.models import Event, NACHRetryPolicy, RevenueLeakCase, UPIRetryBudget
from torque.state_machine import sync_control_group

SUBSCRIPTION_FAILED = "subscription.charged.failed"
SUBSCRIPTION_CHARGED = "subscription.charged"


def subscription_failure_buffer_seconds() -> int:
    """The §2.3 buffer delay for `subscription.charged.failed` (default 30 s,
    `PolicyConfig.subscription_failure_buffer_seconds`)."""
    return get_policy().subscription_failure_buffer_seconds


def resolve_subscription_buffered_event(session: Session, *, event_id) -> BufferOutcome:
    event = session.get(Event, event_id)
    if event is None or event.processed or event.type != SUBSCRIPTION_FAILED:
        return BufferOutcome.NOOP

    if _has_interim_charge(session, event):
        event.processed = True
        session.flush()
        return BufferOutcome.SELF_RECOVERED

    return create_subscription_case(session, event=event)


def _has_interim_charge(session: Session, failure_event: Event) -> bool:
    sub_id = payloads.subscription_id(failure_event.raw_payload or {})
    if not sub_id:
        return False
    for charge in session.scalars(
        select(Event)
        .where(Event.merchant_id == failure_event.merchant_id)
        .where(Event.type == SUBSCRIPTION_CHARGED)
        .where(Event.received_at >= failure_event.received_at)
    ):
        if payloads.subscription_id(charge.raw_payload or {}) == sub_id:
            return True
    return False


def create_subscription_case(session: Session, *, event: Event) -> BufferOutcome:
    existing = session.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.source_event_id == event.event_id)
    ).first()
    if existing is not None:
        if not event.processed:
            event.processed = True
            session.flush()
        return BufferOutcome.NOOP

    payload = event.raw_payload or {}
    counterparty, _mc = resolve_counterparty(
        session,
        merchant_id=event.merchant_id,
        phone=payloads.contact_phone(payload),
        email=payloads.contact_email(payload),
    )
    context = payloads.subscription_failure_context(payload)

    scope = TenantScope(session, event.merchant_id)
    case = RevenueLeakCase(
        leg_type=LegType.SUBSCRIPTION_FAILURE,
        source_event_id=event.event_id,
        counterparty_id=counterparty.counterparty_id,
        amount_at_risk=payloads.amount_rupees(payload),
        status=CaseStatus.DETECTED,
        context=context,
    )
    scope.add(case)
    session.flush()  # _guard_case validates the typed context here

    sync_control_group(session, case)
    _seed_rail_budget(
        session, merchant_id=event.merchant_id, context=context, payload=payload
    )
    apply_active_hold_if_any(session, case)

    # Module 8 §8.5 item 1 — score the case on creation.
    from torque.scoring.score import score_case

    score_case(session, case)

    event.processed = True
    session.flush()
    return BufferOutcome.CASE_CREATED


# --- rail-specific seeding (§2.7 / Part A §3 / D-016 / D-072) --------------


def _seed_rail_budget(
    session: Session, *, merchant_id: str, context: dict, payload: dict
) -> None:
    mandate_type = MandateType(context["mandate_type"])
    mandate_id = context["mandate_id"]

    if mandate_type is MandateType.UPI_AUTOPAY:
        if mandate_id:
            _seed_upi_retry_budget(session, merchant_id=merchant_id, mandate_id=mandate_id)
    elif mandate_type is MandateType.NACH:
        if mandate_id:
            _seed_nach_retry_policy(
                session, merchant_id=merchant_id, mandate_id=mandate_id, payload=payload
            )
    elif mandate_type is MandateType.CARD:
        seed_card_retry_budget(session, merchant_id=merchant_id, payload=payload)


def _seed_upi_retry_budget(session: Session, *, merchant_id: str, mandate_id: str) -> None:
    """Upsert the `UPIRetryBudget` for this mandate to `attempts_used = 1` (the
    failed charge is the original attempt — Part A §3). Idempotent: seed if
    absent, no-op if present. `hard_cap` stays at the NPCI-locked default 3.
    Per-decline increments and `mandate_cancelled_at` are Module 5."""
    existing = session.scalars(
        select(UPIRetryBudget)
        .where(UPIRetryBudget.merchant_id == merchant_id)
        .where(UPIRetryBudget.mandate_id == mandate_id)
    ).first()
    if existing is not None:
        return
    TenantScope(session, merchant_id).add(
        UPIRetryBudget(mandate_id=mandate_id, attempts_used=1)
    )
    session.flush()


def _seed_nach_retry_policy(
    session: Session, *, merchant_id: str, mandate_id: str, payload: dict
) -> None:
    """Upsert the `NACHRetryPolicy` for this mandate: a failed charge means the
    presentment was returned unpaid → `clearing_cycle_status = RETURNED`,
    `dishonour_count_this_fy = 1`. `return_reason_code` is left `None` at
    ingestion — the real NPCI NACH return code arrives via the bank return file
    (Module 5), not this webhook's generic `error_code`. `retry_eligible_after`
    (next batch clearing window) is Module 5's to compute. Idempotent."""
    existing = session.scalars(
        select(NACHRetryPolicy)
        .where(NACHRetryPolicy.merchant_id == merchant_id)
        .where(NACHRetryPolicy.mandate_id == mandate_id)
    ).first()
    if existing is not None:
        return
    TenantScope(session, merchant_id).add(
        NACHRetryPolicy(
            mandate_id=mandate_id,
            clearing_cycle_status=ClearingCycleStatus.RETURNED,
            return_reason_code=None,
            retry_eligible_after=None,
            dishonour_count_this_fy=1,
        )
    )
    session.flush()
