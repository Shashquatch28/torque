"""Module 7 §7.1.2 — indirect match (customer paid directly, no Torque link).

Match by `(merchant_id, counterparty_id, amount)` against open cases; exactly one
match → attribute to it, `AGENT_ASSISTED` iff Torque executed an `Action` for the
case within the attribution window (24h), else `SELF_RECOVERED`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.enums import CaseEventType, CaseStatus, LegType, RecoveryType
from torque.models import CaseEvent, Event
from torque.reconciliation.reconcile import ReconcileOutcome, reconcile_event


def _capture_event(db, merchant, *, amount, phone, key, etype="payment.captured"):
    raw = json.loads(
        razorpay_payment_body(
            event=etype,
            amount_paise=int(Decimal(str(amount)) * 100),
            contact=phone,
        )
    )
    ev = Event(merchant_id=merchant.merchant_id, type=etype, idempotency_key=key, raw_payload=raw)
    db.add(ev)
    db.flush()
    return ev


def _reconciled_events(db, case):
    return db.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .where(CaseEvent.event_type == CaseEventType.PAYMENT_RECONCILED)
    ).all()


def test_single_match_with_recent_action_is_agent_assisted(
    db, make_active_run, make_action, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty(phone="+919800000001")
    case, run, _ = make_active_run(
        merchant=m, counterparty=cp,
        root_cause_code="ISSUER_SOFT_DECLINE_OTHER", amount_at_risk=Decimal("499.00"),
    )
    make_action(case=case, run=run)  # a Torque action executed ~now → within 24h
    ev = _capture_event(db, m, amount=Decimal("499.00"), phone="+919800000001", key="evt_aa_1")

    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.RECOVERED

    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED
    assert case.recovered_amount == Decimal("499.00")
    assert case.closed_at is not None
    assert len(_reconciled_events(db, case)) == 1


def test_single_match_without_action_is_self_recovered(
    db, make_case, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty(phone="+919811110000")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("1200.00"),
    )
    ev = _capture_event(db, m, amount=Decimal("1200.00"), phone="+919811110000", key="evt_sr_1")

    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.RECOVERED
    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovery_type is RecoveryType.SELF_RECOVERED
    assert case.recovered_amount == Decimal("1200.00")


def test_old_action_outside_window_is_self_recovered(
    db, make_case, make_merchant, make_counterparty, make_action
):
    m = make_merchant()
    cp = make_counterparty(phone="+919822220000")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("500.00"),
    )
    act = make_action(case=case)
    act.executed_at = datetime.now(UTC) - timedelta(hours=48)  # well outside 24h
    db.flush()
    ev = _capture_event(db, m, amount=Decimal("500.00"), phone="+919822220000", key="evt_old_1")

    reconcile_event(db, event_id=ev.event_id)
    db.refresh(case)
    assert case.recovery_type is RecoveryType.SELF_RECOVERED


def test_amount_mismatch_is_not_a_match(db, make_case, make_merchant, make_counterparty):
    m = make_merchant()
    cp = make_counterparty(phone="+919833330000")
    make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("500.00"),
    )
    ev = _capture_event(db, m, amount=Decimal("999.00"), phone="+919833330000", key="evt_mm_1")

    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.NO_MATCH


def test_reconcile_is_tenant_scoped(db, make_case, make_merchant, make_counterparty):
    """A merchant-B case is never reconciled by a merchant-A payment even with a
    shared counterparty and equal amount."""
    a, b = make_merchant(), make_merchant()
    cp = make_counterparty(phone="+919844440000")
    case_b = make_case(
        merchant=b, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("777.00"),
    )
    ev = _capture_event(db, a, amount=Decimal("777.00"), phone="+919844440000", key="evt_ten_1")

    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.NO_MATCH
    db.refresh(case_b)
    assert case_b.status is CaseStatus.PLAYBOOK_ACTIVE  # untouched


def test_subscription_charged_matches_a_subscription_failure_case(
    db, make_case, make_merchant, make_counterparty, make_action
):
    from tests.conftest import razorpay_subscription_body

    m = make_merchant()
    cp = make_counterparty(phone="+919855550000")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.SUBSCRIPTION_FAILURE,
        status=CaseStatus.PLAYBOOK_ACTIVE, amount_at_risk=Decimal("299.00"),
        context={
            "mandate_id": "m1", "mandate_type": "UPI_AUTOPAY",
            "billing_cycle": "3", "subscription_id": "sub_ABC",
        },
    )
    make_action(case=case)
    raw = json.loads(
        razorpay_subscription_body(
            event="subscription.charged", amount_paise=29900,
            subscription_id="sub_ABC", contact="+919855550000",
        )
    )
    ev = Event(
        merchant_id=m.merchant_id, type="subscription.charged",
        idempotency_key="evt_sc_1", raw_payload=raw,
    )
    db.add(ev)
    db.flush()

    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.RECOVERED
    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED
