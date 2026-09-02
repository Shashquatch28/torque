"""Leg 2 — `checkout.abandoned` ingestion (Blueprint §2.4 / §2.6).

Checkout abandonment has **no Razorpay webhook**. The demo-scope path (the
confirmed default, Part D item 1) is a signed internal injection endpoint
(`torque.api.checkout_injection`) that verifies an HMAC over the raw body, writes
one `Event(type="checkout.abandoned")`, and enqueues `create_checkout_case_task`.
There is **no self-recovery buffer** (§2.3) — the task runs immediately, in one
`session_scope`.

`create_checkout_case` completes the §2.4 cross-leg Merge in the **reverse
direction** (symmetric with the Leg-1 live direction in
`cases.create_or_attach_case`): a `checkout.abandoned` arriving after an open
`PAYMENT_DEGRADATION` case for the same `(merchant, counterparty)` whose
originating `Event`'s `order_id == cart_id`, within
`PolicyConfig.cross_leg_dedup_window_hours`, creates the `CHECKOUT_ABANDONMENT`
case and immediately supersedes it into that payment case
(`superseded_by_case_id`), carrying its context into the survivor's
`context["merged_abandonment_context"]`. The superseded case keeps its `status`.

**No new `CaseEventType`** (Option A / D-059 / D-068): the merge is fully
reconstructable from `superseded_by_case_id` + the survivor's merged context +
each case's `source_event` and `STATUS_CHANGED` history.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.enums import CaseStatus, LegType
from torque.ingestion import payloads
from torque.ingestion.dedup import find_supersedable_payment_case
from torque.ingestion.identity import resolve_counterparty
from torque.ingestion.outcomes import BufferOutcome
from torque.ingestion.systemic import apply_active_hold_if_any
from torque.models import Event, RevenueLeakCase
from torque.state_machine import sync_control_group

CHECKOUT_ABANDONED = "checkout.abandoned"


def create_checkout_case(session: Session, *, event_id) -> BufferOutcome:
    event = session.get(Event, event_id)
    if event is None or event.processed or event.type != CHECKOUT_ABANDONED:
        return BufferOutcome.NOOP

    existing = session.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.source_event_id == event.event_id)
    ).first()
    if existing is not None:
        event.processed = True
        session.flush()
        return BufferOutcome.NOOP

    payload = event.raw_payload or {}
    counterparty, _mc = resolve_counterparty(
        session,
        merchant_id=event.merchant_id,
        phone=payloads.checkout_contact_phone(payload),
        email=payloads.checkout_contact_email(payload),
    )
    context = payloads.checkout_abandonment_context(payload)

    payment_case = find_supersedable_payment_case(
        session,
        merchant_id=event.merchant_id,
        counterparty_id=counterparty.counterparty_id,
        cart_id=payloads.checkout_cart_id(payload),
        now=datetime.now(UTC),
    )

    scope = TenantScope(session, event.merchant_id)
    case = RevenueLeakCase(
        leg_type=LegType.CHECKOUT_ABANDONMENT,
        source_event_id=event.event_id,
        counterparty_id=counterparty.counterparty_id,
        amount_at_risk=payloads.checkout_cart_value_rupees(payload),
        status=CaseStatus.DETECTED,
        context=context,
    )
    scope.add(case)
    session.flush()  # _guard_case validates the typed context here

    sync_control_group(session, case)

    if payment_case is not None:
        # §2.4 reverse Merge: the abandonment is the narrower case — supersede it
        # into the pre-existing PAYMENT_DEGRADATION case, which stays canonical.
        # No status change on the superseded case; no new CaseEventType.
        case.superseded_by_case_id = payment_case.case_id
        payment_case.context = {
            **(payment_case.context or {}),
            "merged_abandonment_context": dict(case.context or {}),
        }
        session.flush()
        event.processed = True
        session.flush()
        return BufferOutcome.CASE_MERGED

    # Canonical abandonment case — the §2.7 systemic hold hook applies.
    apply_active_hold_if_any(session, case)
    event.processed = True
    session.flush()
    return BufferOutcome.CASE_CREATED
