"""Leg-1 `RevenueLeakCase` creation — Blueprint §2.4 / §2.7 (Milestone 7b).

`create_or_attach_case` is the single path from a buffered `payment.failed`
`Event` to a `PAYMENT_DEGRADATION` case. It:

1. is idempotent — if a case already exists for the `Event`, it only ensures
   `Event.processed` and returns;
2. resolves / creates the `Counterparty` + `Merchant_Counterparty`;
3. runs the §2.4 cross-leg dedup check and, if an open `CHECKOUT_ABANDONMENT`
   case matches, carries that case's context into the new one and points its
   `superseded_by_case_id` at the new case (its own `status` is left untouched —
   there is no `→ CANCELLED` edge and M7b invents none);
4. inserts the case in `DETECTED` via `TenantScope`, with a strictly-validated
   `PaymentDegradationContext`;
5. seeds `CardRetryBudget` to 1 for card payments (§2.7 / Part A §3) — same
   transaction, idempotent, keyed by `COALESCE(token_id, card_id)`;
6. sets `Event.processed = True`.

The caller (`buffer.resolve_buffered_event`, run inside the Celery task's
`session_scope`) owns the transaction — every write here is one atomic unit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.enums import CaseStatus, LegType
from torque.ingestion import payloads
from torque.ingestion.dedup import find_supersedable_case
from torque.ingestion.identity import resolve_counterparty
from torque.ingestion.outcomes import BufferOutcome
from torque.ingestion.systemic import apply_active_hold_if_any
from torque.models import CardRetryBudget, Event, RevenueLeakCase
from torque.state_machine import sync_control_group


def create_or_attach_case(session: Session, *, event: Event) -> BufferOutcome:
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

    context = payloads.payment_degradation_context(payload)
    abandonment = find_supersedable_case(
        session,
        merchant_id=event.merchant_id,
        counterparty_id=counterparty.counterparty_id,
        order_id=payloads.order_id(payload),
        now=datetime.now(UTC),
    )
    if abandonment is not None:
        # §2.4: "no signal is thrown away" — carry the abandonment's context
        # into the surviving case's diagnostic input.
        context["merged_abandonment_context"] = dict(abandonment.context or {})

    scope = TenantScope(session, event.merchant_id)
    case = RevenueLeakCase(
        leg_type=LegType.PAYMENT_DEGRADATION,
        source_event_id=event.event_id,
        counterparty_id=counterparty.counterparty_id,
        amount_at_risk=payloads.amount_rupees(payload),
        status=CaseStatus.DETECTED,
        context=context,
    )
    scope.add(case)
    session.flush()  # _guard_case validates the typed context here

    sync_control_group(session, case)

    merged = abandonment is not None
    if merged:
        abandonment.superseded_by_case_id = case.case_id

    if payloads.is_card_payment(payload):
        _seed_card_retry_budget(session, merchant_id=event.merchant_id, payload=payload)

    # §2.7: if a NETWORK_WIDE SystemicEvent is active for this merchant, the new
    # case is born SYSTEMIC_HOLD rather than DETECTED (Milestone 7c). No-op
    # otherwise — the M7b path is unchanged.
    apply_active_hold_if_any(session, case)

    event.processed = True
    session.flush()
    return BufferOutcome.CASE_MERGED if merged else BufferOutcome.CASE_CREATED


def _seed_card_retry_budget(session: Session, *, merchant_id: str, payload: dict) -> None:
    """Upsert the `CardRetryBudget` for this card to attempt-count 1 (§2.7 /
    Part A §3). Idempotent: the originating decline seeds the row once; every
    subsequent increment is a Module 5 `RETRY_PAYMENT` concern. Multi-decline
    increment-per-originating-event is deferred to Module 5's retry path.

    The `card_token_hash` column (name inherited from the Module-1 schema, not
    renamed here) holds the Razorpay tokenised card reference
    `COALESCE(token_id, card_id)` — no PAN, no hashing in M7b (see
    `payloads.card_instrument_ref`; keyed-HMAC/pepper hardening is deferred). No
    row is written when the payload carries no card instrument reference.
    """
    ref = payloads.card_instrument_ref(payload)
    if not ref:
        return
    existing = session.scalars(
        select(CardRetryBudget)
        .where(CardRetryBudget.merchant_id == merchant_id)
        .where(CardRetryBudget.card_token_hash == ref)
    ).first()
    if existing is not None:
        return
    scope = TenantScope(session, merchant_id)
    scope.add(
        CardRetryBudget(
            card_token_hash=ref,
            attempts_used_24h=1,
            attempts_used_30d=1,
            hard_stop=False,
            hard_stop_reason=None,
        )
    )
    session.flush()
