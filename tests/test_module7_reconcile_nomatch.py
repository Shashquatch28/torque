"""Module 7 §7.1.4 — no open case matched.

A pre-diagnosis (`DETECTED` / `DIAGNOSING`) case for `(merchant, counterparty,
amount)` → the customer self-paid before Torque could act: close it `CANCELLED` /
`SELF_RECOVERED`. Otherwise there is nothing Torque tracked to reconcile.
"""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.enums import CaseEventType, CaseStatus, LegType, RecoveryType
from torque.models import CaseEvent, Event
from torque.reconciliation.reconcile import ReconcileOutcome, reconcile_event


def _capture(db, merchant, *, amount, phone, key):
    raw = json.loads(
        razorpay_payment_body(
            event="payment.captured",
            amount_paise=int(Decimal(str(amount)) * 100),
            contact=phone,
        )
    )
    ev = Event(
        merchant_id=merchant.merchant_id, type="payment.captured",
        idempotency_key=key, raw_payload=raw,
    )
    db.add(ev)
    db.flush()
    return ev


def test_detected_case_self_paid_is_cancelled(db, make_case, make_merchant, make_counterparty):
    m = make_merchant()
    cp = make_counterparty(phone="+919888880001")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.DETECTED, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("640.00"),
    )
    ev = _capture(db, m, amount=Decimal("640.00"), phone="+919888880001", key="evt_nm_1")

    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.SELF_PAID_CANCELLED

    db.refresh(case)
    assert case.status is CaseStatus.CANCELLED
    assert case.recovery_type is RecoveryType.SELF_RECOVERED
    assert case.closed_at is not None
    events = db.scalars(
        select(CaseEvent).where(CaseEvent.case_id == case.case_id).order_by(CaseEvent.event_seq_id)
    ).all()
    types = [e.event_type for e in events]
    assert CaseEventType.STATUS_CHANGED in types
    assert CaseEventType.PAYMENT_RECONCILED in types
    sc = next(e for e in events if e.event_type == CaseEventType.STATUS_CHANGED)
    assert sc.payload["to_status"] == CaseStatus.CANCELLED.value
    assert sc.payload["trigger"] == "customer_self_paid"


def test_diagnosing_case_self_paid_is_cancelled(db, make_case, make_merchant, make_counterparty):
    m = make_merchant()
    cp = make_counterparty(phone="+919888880002")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.DIAGNOSING, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("120.00"),
    )
    ev = _capture(db, m, amount=Decimal("120.00"), phone="+919888880002", key="evt_nm_2")
    assert reconcile_event(db, event_id=ev.event_id) is ReconcileOutcome.SELF_PAID_CANCELLED
    db.refresh(case)
    assert case.status is CaseStatus.CANCELLED


def test_truly_unknown_payment_is_no_match(db, make_merchant, make_counterparty):
    m = make_merchant()
    make_counterparty(phone="+919888880003")  # known counterparty, but no case
    ev = _capture(db, m, amount=Decimal("999.00"), phone="+919888880003", key="evt_nm_3")
    assert reconcile_event(db, event_id=ev.event_id) is ReconcileOutcome.NO_MATCH


def test_unknown_counterparty_is_no_match(db, make_merchant):
    m = make_merchant()
    ev = _capture(db, m, amount=Decimal("50.00"), phone="+910000000404", key="evt_nm_4")
    assert reconcile_event(db, event_id=ev.event_id) is ReconcileOutcome.NO_MATCH


def test_detected_case_amount_mismatch_is_no_match(db, make_case, make_merchant, make_counterparty):
    m = make_merchant()
    cp = make_counterparty(phone="+919888880005")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.DETECTED, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("500.00"),
    )
    ev = _capture(db, m, amount=Decimal("300.00"), phone="+919888880005", key="evt_nm_5")
    assert reconcile_event(db, event_id=ev.event_id) is ReconcileOutcome.NO_MATCH
    db.refresh(case)
    assert case.status is CaseStatus.DETECTED  # untouched
