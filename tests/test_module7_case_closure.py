"""Module 7 §7.2 — case closure.

Full amount → `RECOVERED`, `recovered_amount = amount_at_risk`, `closed_at`.
B2B partial → `PARTIALLY_RECOVERED` (case stays open), the matching
`B2BInvoice.outstanding_amount` decremented and `amount_at_risk` follows.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.enums import CaseEventType, CaseStatus, LegType, RecoveryType
from torque.models import B2BInvoice, CaseEvent, Event
from torque.reconciliation.reconcile import ReconcileOutcome, reconcile_event


def _b2b_case(db, make_case, m, cp, invoices):
    total = sum((amt for amt, _ in invoices), Decimal("0"))
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={},
        status=CaseStatus.PLAYBOOK_ACTIVE, amount_at_risk=total,
    )
    for amt, due in invoices:
        db.add(
            B2BInvoice(
                case_id=case.case_id, merchant_id=m.merchant_id,
                counterparty_id=cp.counterparty_id,
                due_date=due, days_overdue=30,
                original_amount=amt, outstanding_amount=amt,
            )
        )
    db.flush()
    return case


def _capture(db, m, *, amount, phone, key):
    raw = json.loads(
        razorpay_payment_body(
            event="payment.captured",
            amount_paise=int(Decimal(str(amount)) * 100), contact=phone,
        )
    )
    ev = Event(
        merchant_id=m.merchant_id, type="payment.captured",
        idempotency_key=key, raw_payload=raw,
    )
    db.add(ev)
    db.flush()
    return ev


def _reconcile_capture(db, m, *, amount, phone, key):
    return reconcile_event(
        db, event_id=_capture(db, m, amount=amount, phone=phone, key=key).event_id
    )


def _outstanding(db, case):
    return sorted(
        db.scalars(select(B2BInvoice).where(B2BInvoice.case_id == case.case_id)).all(),
        key=lambda i: i.due_date,
    )


def test_b2b_partial_payment_stays_open_and_decrements_oldest_invoice(
    db, make_case, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty(phone="+919899990001")
    case = _b2b_case(
        db, make_case, m, cp,
        [(Decimal("1000.00"), date(2026, 1, 1)), (Decimal("2000.00"), date(2026, 2, 1))],
    )
    ev = _capture(db, m, amount=Decimal("1200.00"), phone="+919899990001", key="evt_cc_1")

    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.PARTIALLY_RECOVERED

    db.refresh(case)
    assert case.status is CaseStatus.PARTIALLY_RECOVERED  # stays open
    assert case.recovered_amount == Decimal("1200.00")
    assert case.amount_at_risk == Decimal("1800.00")  # Σ outstanding (INV-33)
    inv = _outstanding(db, case)
    assert inv[0].outstanding_amount == Decimal("0.00")   # oldest cleared
    assert inv[1].outstanding_amount == Decimal("1800.00")  # 2000 - remaining 200


def test_b2b_second_partial_closes_the_case(
    db, make_case, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty(phone="+919899990002")
    case = _b2b_case(db, make_case, m, cp, [(Decimal("3000.00"), date(2026, 1, 1))])
    _reconcile_capture(db, m, amount="1000.00", phone="+919899990002", key="evt_cc_2a")
    db.refresh(case)
    assert case.status is CaseStatus.PARTIALLY_RECOVERED
    assert case.amount_at_risk == Decimal("2000.00")

    outcome = _reconcile_capture(db, m, amount="2000.00", phone="+919899990002", key="evt_cc_2b")
    assert outcome is ReconcileOutcome.RECOVERED
    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovered_amount == Decimal("3000.00")
    assert case.closed_at is not None
    # the two-hop PARTIALLY_RECOVERED -> PLAYBOOK_ACTIVE -> RECOVERED is audited
    scs = [
        e.payload["to_status"]
        for e in db.scalars(
            select(CaseEvent)
            .where(CaseEvent.case_id == case.case_id)
            .where(CaseEvent.event_type == CaseEventType.STATUS_CHANGED)
            .order_by(CaseEvent.event_seq_id)
        ).all()
    ]
    assert scs[-2:] == [CaseStatus.PLAYBOOK_ACTIVE.value, CaseStatus.RECOVERED.value]


def test_b2b_full_lump_payment_recovers_directly(
    db, make_case, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty(phone="+919899990003")
    case = _b2b_case(
        db, make_case, m, cp,
        [(Decimal("500.00"), date(2026, 1, 1)), (Decimal("500.00"), date(2026, 2, 1))],
    )
    outcome = _reconcile_capture(db, m, amount="1000.00", phone="+919899990003", key="evt_cc_3")
    assert outcome is ReconcileOutcome.RECOVERED
    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert all(i.outstanding_amount == Decimal("0.00") for i in _outstanding(db, case))


def test_non_b2b_partial_payment_does_not_match(
    db, make_case, make_merchant, make_counterparty
):
    """A subscription/card failure is settled in full or not at all — a partial
    payment is not a recovery (Blueprint §7.2 scopes partials to B2B)."""
    m = make_merchant()
    cp = make_counterparty(phone="+919899990004")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.SUBSCRIPTION_FAILURE,
        status=CaseStatus.PLAYBOOK_ACTIVE, amount_at_risk=Decimal("500.00"),
        context={
            "mandate_id": "m", "mandate_type": "CARD",
            "billing_cycle": "1", "subscription_id": "s",
        },
    )
    outcome = _reconcile_capture(db, m, amount="200.00", phone="+919899990004", key="evt_cc_4")
    assert outcome is ReconcileOutcome.NO_MATCH
    db.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE


def test_escalated_to_human_case_is_recovered_by_a_payment(
    db, make_case, make_merchant, make_counterparty, make_action
):
    """A payment landing for a case waiting in the human queue closes it and
    clears the queue entry (queue consistency — not Agent Console behaviour)."""
    from torque.coordination import human_queue

    m = make_merchant()
    cp = make_counterparty(phone="+919899990005")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.ESCALATED_TO_HUMAN, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("777.00"),
    )
    make_action(case=case)
    human_queue.enqueue(
        db, case=case, reason=human_queue.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS
    )

    outcome = _reconcile_capture(db, m, amount="777.00", phone="+919899990005", key="evt_cc_5")
    assert outcome is ReconcileOutcome.RECOVERED
    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED
    assert human_queue.list_for_merchant(db, m.merchant_id) == []  # dequeued
