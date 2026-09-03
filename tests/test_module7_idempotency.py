"""Module 7 — reconciliation is idempotent and concurrency-safe.

A duplicate / redelivered success `Event` never double-closes a case or writes a
second `PAYMENT_RECONCILED`; two workers racing on the same case cannot both
recover it (the matched case rows are `SELECT … FOR UPDATE`).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.db.session import SessionLocal
from torque.enums import CaseEventType, CaseStatus, LegType
from torque.models import (
    CaseEvent,
    Counterparty,
    Event,
    Merchant,
    RevenueLeakCase,
)
from torque.reconciliation.reconcile import ReconcileOutcome, reconcile_event


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


def test_rerun_on_processed_event_is_noop(db, make_case, make_merchant, make_counterparty):
    m = make_merchant()
    cp = make_counterparty(phone="+919700000001")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("400.00"),
    )
    ev = _capture(db, m, amount=Decimal("400.00"), phone="+919700000001", key="evt_id_1")

    assert reconcile_event(db, event_id=ev.event_id) is ReconcileOutcome.RECOVERED
    # redelivery of the SAME event
    assert reconcile_event(db, event_id=ev.event_id) is ReconcileOutcome.NOOP

    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    reconciled = db.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .where(CaseEvent.event_type == CaseEventType.PAYMENT_RECONCILED)
    ).all()
    assert len(reconciled) == 1  # not doubled


def test_missing_and_wrong_type_events_are_noop(db, make_merchant, make_event):
    assert reconcile_event(db, event_id=uuid.uuid4()) is ReconcileOutcome.NOOP
    m = make_merchant()
    ev = make_event(m, type="payment.failed")  # not a reconciliation type
    assert reconcile_event(db, event_id=ev.event_id) is ReconcileOutcome.NOOP


def test_second_distinct_payment_for_a_closed_case_is_noop(
    db, make_case, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty(phone="+919700000002")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("500.00"),
    )
    ev_a = _capture(db, m, amount=Decimal("500.00"), phone="+919700000002", key="evt_id_2a")
    reconcile_event(db, event_id=ev_a.event_id)
    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED

    # a second (duplicate) capture — the case is already terminal
    ev_b = _capture(db, m, amount=Decimal("500.00"), phone="+919700000002", key="evt_id_2b")
    outcome = reconcile_event(db, event_id=ev_b.event_id)
    assert outcome is ReconcileOutcome.NO_MATCH


# --- true concurrency (two connections) --------------------------------


def test_two_workers_race_one_recovery(engine):
    """Two `payment.captured` events for the same case on two connections: the
    first (committed) recovery closes it; the second worker's `SELECT … FOR
    UPDATE` match then sees a terminal case and no-ops — exactly one recovery,
    one `PAYMENT_RECONCILED`."""
    ids = {}
    setup = SessionLocal(bind=engine.connect())
    try:
        m = Merchant(merchant_id="acc_m7_conc", channels_enabled=[], risk_appetite_config={})
        cp = Counterparty(
            name="C", phone="+919700009999", email="m7c@x.test",
            payment_failure_nudge_consent=True,
        )
        setup.add_all([m, cp])
        setup.flush()
        ev_ids = []
        src = Event(
            merchant_id=m.merchant_id, type="payment.failed",
            idempotency_key="evt_m7c_src", raw_payload={},
        )
        setup.add(src)
        setup.flush()
        case = RevenueLeakCase(
            merchant_id=m.merchant_id, leg_type=LegType.PAYMENT_DEGRADATION,
            source_event_id=src.event_id, counterparty_id=cp.counterparty_id,
            amount_at_risk=Decimal("900.00"), status=CaseStatus.PLAYBOOK_ACTIVE,
            context={"gateway": "razorpay"},
        )
        setup.add(case)
        setup.flush()
        for i in range(2):
            raw = json.loads(
                razorpay_payment_body(
                    event="payment.captured", amount_paise=90000, contact="+919700009999"
                )
            )
            e = Event(
                merchant_id=m.merchant_id, type="payment.captured",
                idempotency_key=f"evt_m7c_{i}", raw_payload=raw,
            )
            setup.add(e)
            setup.flush()
            ev_ids.append(e.event_id)
        setup.commit()
        ids = {"merchant": m.merchant_id, "case": case.case_id, "events": ev_ids}
    finally:
        setup.close()

    now = datetime(2030, 1, 1, tzinfo=UTC)
    conn_a, conn_b = engine.connect(), engine.connect()
    sa, sb = SessionLocal(bind=conn_a), SessionLocal(bind=conn_b)
    try:
        out_a = reconcile_event(sa, event_id=ids["events"][0], now=now)
        sa.commit()
        out_b = reconcile_event(sb, event_id=ids["events"][1], now=now)
        sb.commit()
        assert out_a is ReconcileOutcome.RECOVERED
        assert out_b is ReconcileOutcome.NO_MATCH  # case already closed
        c = sb.get(RevenueLeakCase, ids["case"])
        assert c.status is CaseStatus.RECOVERED
        recon = sb.scalars(
            select(CaseEvent)
            .where(CaseEvent.case_id == ids["case"])
            .where(CaseEvent.event_type == CaseEventType.PAYMENT_RECONCILED)
        ).all()
        assert len(recon) == 1
    finally:
        sa.close()
        sb.close()
        conn_a.close()
        conn_b.close()
        _cleanup(engine, ids["merchant"], "+919700009999")


def _cleanup(engine, merchant_id: str, phone: str) -> None:
    from sqlalchemy import text

    conn = engine.connect()
    try:
        conn.execute(text("ALTER TABLE case_event DISABLE TRIGGER case_event_no_mutate"))
        conn.execute(
            text(
                "DELETE FROM case_event WHERE case_id IN "
                "(SELECT case_id FROM revenue_leak_case WHERE merchant_id = :m)"
            ),
            {"m": merchant_id},
        )
        conn.execute(text("ALTER TABLE case_event ENABLE TRIGGER case_event_no_mutate"))
        for t in ("revenue_leak_case", "event", "merchant"):
            conn.execute(text(f"DELETE FROM {t} WHERE merchant_id = :m"), {"m": merchant_id})
        conn.execute(text("DELETE FROM counterparty WHERE phone = :p"), {"p": phone})
        conn.commit()
    finally:
        conn.close()
