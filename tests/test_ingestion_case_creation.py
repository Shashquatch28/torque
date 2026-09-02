"""Milestone 7b — Leg-1 `PAYMENT_DEGRADATION` case creation."""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.enums import CaseStatus, LegType
from torque.ingestion.cases import create_or_attach_case
from torque.ingestion.outcomes import BufferOutcome
from torque.models import Counterparty, MerchantCounterparty, RevenueLeakCase


def _payload(**kw) -> dict:
    return json.loads(razorpay_payment_body(**kw))


def _event(make_event, m, **body):
    return make_event(
        m, type="payment.failed", raw_payload=_payload(event="payment.failed", **body)
    )


def _the_case(db, m):
    return db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()


def test_case_has_expected_shape(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, amount_paise=49900, error_code="GATEWAY_ERROR")
    out = create_or_attach_case(db, event=ev)

    assert out is BufferOutcome.CASE_CREATED
    case = _the_case(db, m)
    assert case.leg_type is LegType.PAYMENT_DEGRADATION
    assert case.status is CaseStatus.DETECTED
    assert case.source_event_id == ev.event_id
    assert case.amount_at_risk == Decimal("499.00")
    assert case.context["gateway"] == "razorpay"
    assert case.context["decline_code"] == "GATEWAY_ERROR"
    assert case.control_group is None  # no cohort assigned
    assert ev.processed is True


def test_ingestion_does_not_classify_hard_decline(db, make_merchant, make_event):
    # error_reason / error_code must NOT be turned into a hard/soft verdict —
    # that is Module 3's job. Ingestion leaves is_hard_decline unset (None).
    m = make_merchant()
    ev = _event(make_event, m, error_code="issuer_declined")
    create_or_attach_case(db, event=ev)
    assert _the_case(db, m).context["is_hard_decline"] is None


def test_missing_amount_defaults_to_zero(db, make_merchant, make_event):
    m = make_merchant()
    body = _payload(event="payment.failed")
    body["payload"]["payment"]["entity"].pop("amount")
    ev = make_event(m, type="payment.failed", raw_payload=body)
    create_or_attach_case(db, event=ev)
    assert _the_case(db, m).amount_at_risk == Decimal("0.00")


def test_counterparty_and_merchant_counterparty_created(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, contact="+919810000123", email="new@buyer.test")
    create_or_attach_case(db, event=ev)

    cp = db.scalars(
        select(Counterparty).where(Counterparty.phone == "+919810000123")
    ).one()
    assert cp.email == "new@buyer.test"
    assert cp.payment_failure_nudge_consent is False
    assert cp.whatsapp_opt_in is False

    mc = db.scalars(
        select(MerchantCounterparty)
        .where(MerchantCounterparty.merchant_id == m.merchant_id)
        .where(MerchantCounterparty.counterparty_id == cp.counterparty_id)
    ).one()
    assert mc.in_control_cohort is None


def test_existing_counterparty_is_reused_by_phone(db, make_merchant, make_event, make_counterparty):
    m = make_merchant()
    existing = make_counterparty(phone="+919820000000", email="old@buyer.test")
    ev = _event(make_event, m, contact="+919820000000", email="somethingelse@buyer.test")
    create_or_attach_case(db, event=ev)
    assert _the_case(db, m).counterparty_id == existing.counterparty_id
    assert len(db.scalars(select(Counterparty)).all()) == 1


def test_second_failure_same_customer_reuses_counterparty(db, make_merchant, make_event):
    m = make_merchant()
    ev1 = _event(make_event, m, payment_id="pay_1", order_id="order_1", contact="+919830000000")
    ev2 = _event(make_event, m, payment_id="pay_2", order_id="order_2", contact="+919830000000")
    create_or_attach_case(db, event=ev1)
    create_or_attach_case(db, event=ev2)
    cases = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).all()
    assert len(cases) == 2
    assert cases[0].counterparty_id == cases[1].counterparty_id


def test_context_passes_the_typed_guard(db, make_merchant, make_event):
    # If the guard rejected the context this would raise on flush.
    m = make_merchant()
    ev = _event(make_event, m)
    create_or_attach_case(db, event=ev)
    case = _the_case(db, m)
    # normalised dict, all PaymentDegradationContext keys present
    assert set(case.context) >= {"gateway", "decline_code", "retry_count", "is_hard_decline"}
