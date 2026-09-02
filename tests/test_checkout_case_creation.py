"""Module 2 Leg 2 — `CHECKOUT_ABANDONMENT` case creation (no merge path here)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from tests.conftest import checkout_abandoned_body
from torque.enums import CaseStatus, LegType, PaymentMethodAttempted
from torque.ingestion.checkout import create_checkout_case
from torque.ingestion.outcomes import BufferOutcome
from torque.ingestion.systemic import run_systemic_detection
from torque.models import Counterparty, MerchantCounterparty, RevenueLeakCase


def _payload(**kw) -> dict:
    return json.loads(checkout_abandoned_body(**kw))


def _event(make_event, m, **body):
    return make_event(m, type="checkout.abandoned", raw_payload=_payload(**body))


def _the_case(db, m):
    return db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()


def test_case_has_expected_shape(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(
        make_event, m, cart_value_paise=49900, drop_stage="otp",
        payment_method_attempted="CARD",
    )
    out = create_checkout_case(db, event_id=ev.event_id)

    assert out is BufferOutcome.CASE_CREATED
    case = _the_case(db, m)
    assert case.leg_type is LegType.CHECKOUT_ABANDONMENT
    assert case.status is CaseStatus.DETECTED
    assert case.source_event_id == ev.event_id
    assert str(case.amount_at_risk) == "499.00"
    assert case.context == {
        "cart_id": "cart_M2001",
        "cart_value": "499.00",
        "drop_stage": "otp",
        "payment_method_attempted": "CARD",
    }
    assert case.superseded_by_case_id is None
    assert ev.processed is True


def test_unknown_payment_method_falls_back_to_none(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, payment_method_attempted="CRYPTO")
    create_checkout_case(db, event_id=ev.event_id)
    assert _the_case(db, m).context["payment_method_attempted"] == PaymentMethodAttempted.NONE.value


def test_counterparty_and_merchant_counterparty_resolved(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, contact="+919811110000", email="cart@buyer.test")
    create_checkout_case(db, event_id=ev.event_id)
    cp = db.scalars(select(Counterparty).where(Counterparty.phone == "+919811110000")).one()
    assert cp.payment_failure_nudge_consent is False
    mc = db.scalars(
        select(MerchantCounterparty)
        .where(MerchantCounterparty.merchant_id == m.merchant_id)
        .where(MerchantCounterparty.counterparty_id == cp.counterparty_id)
    ).one()
    assert mc.in_control_cohort is None


def test_thin_payload_yields_sparse_case_not_error(db, make_merchant, make_event):
    m = make_merchant()
    ev = make_event(m, type="checkout.abandoned", raw_payload={"event": "checkout.abandoned"})
    out = create_checkout_case(db, event_id=ev.event_id)
    assert out is BufferOutcome.CASE_CREATED
    case = _the_case(db, m)
    assert case.context["cart_id"] == ""
    assert case.context["drop_stage"] == "unknown"
    assert case.context["payment_method_attempted"] == "NONE"


def test_redelivery_is_idempotent(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m)
    assert create_checkout_case(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED
    assert create_checkout_case(db, event_id=ev.event_id) is BufferOutcome.NOOP
    rows = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).all()
    assert len(rows) == 1


def test_wrong_type_and_missing_event_are_noop(db, make_merchant, make_event):
    m = make_merchant()
    other = make_event(m, type="payment.failed", raw_payload={"event": "payment.failed"})
    assert create_checkout_case(db, event_id=other.event_id) is BufferOutcome.NOOP
    assert create_checkout_case(db, event_id=uuid.uuid4()) is BufferOutcome.NOOP


def test_systemic_hold_applies_to_a_canonical_abandonment_case(
    db, make_merchant, make_event, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    run_systemic_detection(db, now=datetime.now(UTC))

    ev = _event(make_event, m, cart_id="cart_lonely")  # no matching payment case
    create_checkout_case(db, event_id=ev.event_id)
    case = _the_case(db, m)
    assert case.status is CaseStatus.SYSTEMIC_HOLD
    assert case.systemic_event_id is not None
