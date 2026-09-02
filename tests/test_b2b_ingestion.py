"""Module 2 Leg 4 — `invoice.overdue` → `B2BInvoice` + case grouping (Blueprint §3)."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from tests.conftest import razorpay_invoice_body
from torque.enums import CaseStatus, LegType
from torque.ingestion import b2b as b2b_mod
from torque.ingestion.b2b import ingest_invoice
from torque.ingestion.outcomes import BufferOutcome
from torque.models import B2BInvoice, Event, RevenueLeakCase


def _payload(**kw) -> dict:
    return json.loads(razorpay_invoice_body(**kw))


def _event(make_event, m, key=None, **body):
    kw = {"type": "invoice.overdue", "raw_payload": _payload(**body)}
    if key is not None:
        kw["idempotency_key"] = key
    return make_event(m, **kw)


def _b2b_cases(db, m):
    return db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
        .where(RevenueLeakCase.leg_type == LegType.B2B_RECEIVABLE)
    ).all()


def _invoices(db, case_id):
    return db.scalars(select(B2BInvoice).where(B2BInvoice.case_id == case_id)).all()


def test_first_overdue_invoice_creates_a_b2b_case(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, amount_paise=100_000, amount_due_paise=60_000)
    out = ingest_invoice(db, event_id=ev.event_id)

    assert out is BufferOutcome.CASE_CREATED
    (case,) = _b2b_cases(db, m)
    assert case.leg_type is LegType.B2B_RECEIVABLE
    assert case.status is CaseStatus.DETECTED
    assert case.context == {}  # B2B takes no context blob
    assert case.source_event_id == ev.event_id
    assert case.amount_at_risk == Decimal("600.00")

    (inv,) = _invoices(db, case.case_id)
    assert inv.original_amount == Decimal("1000.00")
    assert inv.outstanding_amount == Decimal("600.00")
    assert inv.outstanding_amount <= inv.original_amount
    assert inv.days_overdue >= 0
    assert inv.gst_inclusive is True
    assert inv.payment_terms == "NET30"
    assert ev.processed is True


def test_second_invoice_same_counterparty_attaches_to_the_open_case(
    db, make_merchant, make_counterparty, make_event
):
    m = make_merchant()
    make_counterparty(phone="+919820000111", email="ap@one.test")
    e1 = _event(make_event, m, key="evt_inv_1", invoice_id="inv_A",
                amount_paise=100_000, amount_due_paise=100_000, contact="+919820000111")
    e2 = _event(make_event, m, key="evt_inv_2", invoice_id="inv_B",
                amount_paise=50_000, amount_due_paise=50_000, contact="+919820000111")

    assert ingest_invoice(db, event_id=e1.event_id) is BufferOutcome.CASE_CREATED
    assert ingest_invoice(db, event_id=e2.event_id) is BufferOutcome.CASE_ATTACHED

    cases = _b2b_cases(db, m)
    assert len(cases) == 1  # one dunning thread
    case = cases[0]
    assert len(_invoices(db, case.case_id)) == 2
    # amount_at_risk = Σ outstanding = 1000 + 500
    assert case.amount_at_risk == Decimal("1500.00")


def test_different_counterparty_gets_its_own_case(db, make_merchant, make_event):
    m = make_merchant()
    _event(make_event, m, key="evt_c1", invoice_id="inv_1", contact="+911", email="one@x.test")
    _event(make_event, m, key="evt_c2", invoice_id="inv_2", contact="+912", email="two@x.test")
    ev1 = db.scalars(select(Event).where(Event.idempotency_key == "evt_c1")).one()
    ev2 = db.scalars(select(Event).where(Event.idempotency_key == "evt_c2")).one()
    ingest_invoice(db, event_id=ev1.event_id)
    ingest_invoice(db, event_id=ev2.event_id)
    assert len(_b2b_cases(db, m)) == 2


def test_no_bundling_into_a_terminal_case(db, make_merchant, make_counterparty, make_event):
    m = make_merchant()
    make_counterparty(phone="+919830000222")
    e1 = _event(make_event, m, key="evt_t1", invoice_id="inv_x", contact="+919830000222")
    ingest_invoice(db, event_id=e1.event_id)
    (case,) = _b2b_cases(db, m)
    case.status = CaseStatus.WRITTEN_OFF  # raw set — terminal
    db.flush()

    e2 = _event(make_event, m, key="evt_t2", invoice_id="inv_y", contact="+919830000222")
    assert ingest_invoice(db, event_id=e2.event_id) is BufferOutcome.CASE_CREATED
    assert len(_b2b_cases(db, m)) == 2  # a fresh case, not the written-off one


def test_redelivery_is_idempotent_create_and_attach(
    db, make_merchant, make_counterparty, make_event
):
    m = make_merchant()
    make_counterparty(phone="+919840000333")
    e1 = _event(make_event, m, key="evt_r1", invoice_id="inv_r1", contact="+919840000333")
    e2 = _event(make_event, m, key="evt_r2", invoice_id="inv_r2", contact="+919840000333")

    ingest_invoice(db, event_id=e1.event_id)
    ingest_invoice(db, event_id=e1.event_id)  # redelivery of the CREATE
    ingest_invoice(db, event_id=e2.event_id)
    ingest_invoice(db, event_id=e2.event_id)  # redelivery of the ATTACH

    (case,) = _b2b_cases(db, m)
    assert len(_invoices(db, case.case_id)) == 2


def test_wrong_type_and_missing_event_are_noop(db, make_merchant, make_event):
    m = make_merchant()
    other = make_event(m, type="payment.failed", raw_payload={"event": "payment.failed"})
    assert ingest_invoice(db, event_id=other.event_id) is BufferOutcome.NOOP
    assert ingest_invoice(db, event_id=uuid.uuid4()) is BufferOutcome.NOOP


def test_outstanding_is_clamped_to_original(db, make_merchant, make_event):
    m = make_merchant()
    # amount_due > amount → must clamp to original
    ev = _event(make_event, m, amount_paise=50_000, amount_due_paise=90_000)
    ingest_invoice(db, event_id=ev.event_id)
    (case,) = _b2b_cases(db, m)
    (inv,) = _invoices(db, case.case_id)
    assert inv.outstanding_amount == Decimal("500.00")
    assert inv.original_amount == Decimal("500.00")


def test_seeding_is_tenant_isolated(db, make_merchant, make_event):
    a, b = make_merchant(), make_merchant()
    ea = _event(make_event, a, key="evt_ta", contact="+91777")
    ingest_invoice(db, event_id=ea.event_id)
    assert len(_b2b_cases(db, a)) == 1
    assert _b2b_cases(db, b) == []


def test_failure_mid_ingest_rolls_everything_back(db, make_merchant, make_event, monkeypatch):
    m = make_merchant()
    ev = _event(make_event, m)

    real = b2b_mod.sync_control_group

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(b2b_mod, "sync_control_group", _boom)

    savepoint = db.begin_nested()
    with pytest.raises(RuntimeError):
        ingest_invoice(db, event_id=ev.event_id)
    savepoint.rollback()
    monkeypatch.setattr(b2b_mod, "sync_control_group", real)

    assert _b2b_cases(db, m) == []
    assert db.scalars(select(B2BInvoice)).all() == []
    assert db.get(Event, ev.event_id).processed is False
