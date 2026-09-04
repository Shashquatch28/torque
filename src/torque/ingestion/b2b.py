"""Leg 4 — `invoice.overdue` ingestion (Blueprint §2.1 / §2.3 / §3 B2B grouping).

No self-recovery buffer (§2.3 — an overdue invoice already implies elapsed time).
The Razorpay webhook writes the `Event` and enqueues `ingest_invoice_task`, which
runs this in one `session_scope`.

**Grouping rule (locked, §3):** on `invoice.overdue`, check for an existing
**open** (non-terminal) `B2B_RECEIVABLE` case for the same
`(merchant_id, counterparty_id)`.
* Found  → the new `B2BInvoice` attaches to that `case_id`; **no new case**.
* Not found → a new `B2B_RECEIVABLE` case is created; the invoice is its first
  `B2BInvoice` row.
There is **no time window** — a case keeps accepting invoices until it reaches a
terminal status. `B2B_RECEIVABLE` cases carry **no context blob** (`{}`).

`case.amount_at_risk` is maintained as Σ `outstanding_amount` across the case's
invoices (the "here's everything you owe" thread — §3). Partial-payment /
`outstanding_amount` decrement, dunning, and case closure are downstream modules.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.enums import CaseStatus, LegType
from torque.ingestion import payloads
from torque.ingestion.identity import resolve_counterparty
from torque.ingestion.outcomes import BufferOutcome
from torque.ingestion.systemic import apply_active_hold_if_any
from torque.models import B2BInvoice, Event, RevenueLeakCase
from torque.state_machine import is_terminal, sync_control_group

INVOICE_OVERDUE = "invoice.overdue"


def ingest_invoice(
    session: Session,
    *,
    event_id,
    on_case_ready: Callable[[RevenueLeakCase], None] | None = None,
) -> BufferOutcome:
    event = session.get(Event, event_id)
    if event is None or event.processed or event.type != INVOICE_OVERDUE:
        return BufferOutcome.NOOP

    # Redelivery after a CREATE committed (the CREATE path stamps source_event_id).
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
        phone=payloads.invoice_contact_phone(payload),
        email=payloads.invoice_contact_email(payload),
    )

    open_b2b = [
        c
        for c in session.scalars(
            select(RevenueLeakCase)
            .where(RevenueLeakCase.merchant_id == event.merchant_id)
            .where(RevenueLeakCase.counterparty_id == counterparty.counterparty_id)
            .where(RevenueLeakCase.leg_type == LegType.B2B_RECEIVABLE)
            .where(RevenueLeakCase.superseded_by_case_id.is_(None))
            .order_by(RevenueLeakCase.opened_at.asc())
        ).all()
        if not is_terminal(c.status, c.leg_type)
    ]
    target_case = open_b2b[0] if open_b2b else None

    original = payloads.invoice_original_rupees(payload)
    outstanding = payloads.invoice_outstanding_rupees(payload, original)
    due = payloads.invoice_due_date(payload)
    days_overdue = max(0, (datetime.now(UTC).date() - due).days) if due is not None else 0

    scope = TenantScope(session, event.merchant_id)

    created = target_case is None
    if created:
        target_case = RevenueLeakCase(
            leg_type=LegType.B2B_RECEIVABLE,
            source_event_id=event.event_id,
            counterparty_id=counterparty.counterparty_id,
            amount_at_risk=outstanding,
            status=CaseStatus.DETECTED,
            context={},
        )
        scope.add(target_case)
        session.flush()
        sync_control_group(session, target_case)
        apply_active_hold_if_any(session, target_case)

    scope.add(
        B2BInvoice(
            case_id=target_case.case_id,
            counterparty_id=counterparty.counterparty_id,
            due_date=due if due is not None else datetime.now(UTC).date(),
            days_overdue=days_overdue,
            original_amount=original,
            outstanding_amount=outstanding,
            gst_inclusive=payloads.invoice_gst_inclusive(payload),
            payment_terms=payloads.invoice_payment_terms(payload),
        )
    )
    session.flush()

    # Keep amount_at_risk = Σ outstanding across the dunning thread (§3).
    total = session.scalar(
        select(func.coalesce(func.sum(B2BInvoice.outstanding_amount), 0)).where(
            B2BInvoice.case_id == target_case.case_id
        )
    )
    target_case.amount_at_risk = total

    # Module 8 §8.5 item 1 — score on creation / re-score on invoice attach
    # (amount_at_risk and days-overdue just changed).
    from torque.scoring.score import score_case

    score_case(session, target_case)

    event.processed = True
    session.flush()

    if on_case_ready is not None:
        # Correct in both branches: `target_case` is either the just-created
        # case or the pre-existing open case this invoice bundled into (§3).
        on_case_ready(target_case)

    return BufferOutcome.CASE_CREATED if created else BufferOutcome.CASE_ATTACHED
