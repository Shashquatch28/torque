"""Milestone 8 — Leg-3 `SUBSCRIPTION_FAILURE` case creation."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from tests.conftest import razorpay_subscription_body
from torque.enums import CaseStatus, LegType, MandateType
from torque.ingestion.outcomes import BufferOutcome
from torque.ingestion.subscription import create_subscription_case
from torque.models import Counterparty, MerchantCounterparty, RevenueLeakCase


def _payload(**kw) -> dict:
    return json.loads(razorpay_subscription_body(**kw))


def _event(make_event, m, **body):
    return make_event(
        m,
        type="subscription.charged.failed",
        raw_payload=_payload(event="subscription.charged.failed", **body),
    )


def _the_case(db, m):
    return db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()


def test_case_has_expected_shape(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, amount_paise=49900, method="upi", paid_count=4)
    out = create_subscription_case(db, event=ev)

    assert out is BufferOutcome.CASE_CREATED
    case = _the_case(db, m)
    assert case.leg_type is LegType.SUBSCRIPTION_FAILURE
    assert case.status is CaseStatus.DETECTED
    assert case.source_event_id == ev.event_id
    assert case.amount_at_risk == Decimal("499.00")
    ctx = case.context
    assert set(ctx) == {"mandate_id", "mandate_type", "billing_cycle", "subscription_id"}
    assert ctx["mandate_type"] == MandateType.UPI_AUTOPAY.value
    assert ctx["subscription_id"] == "sub_M8001"
    assert ctx["mandate_id"] == "token_M8001"
    assert ctx["billing_cycle"] == "5"
    assert ev.processed is True


def test_counterparty_and_merchant_counterparty_resolved(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, contact="+919812345678", email="sub@buyer.test")
    create_subscription_case(db, event=ev)

    cp = db.scalars(
        select(Counterparty).where(Counterparty.phone == "+919812345678")
    ).one()
    assert cp.payment_failure_nudge_consent is False
    mc = db.scalars(
        select(MerchantCounterparty)
        .where(MerchantCounterparty.merchant_id == m.merchant_id)
        .where(MerchantCounterparty.counterparty_id == cp.counterparty_id)
    ).one()
    assert mc.in_control_cohort is None


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("upi", MandateType.UPI_AUTOPAY),
        ("card", MandateType.CARD),
        ("emandate", MandateType.NACH),
        ("nach", MandateType.NACH),
        ("netbanking", MandateType.NACH),
        ("something_new", MandateType.NACH),
    ],
)
def test_mandate_type_mapping(db, make_merchant, make_event, method, expected):
    m = make_merchant()
    ev = _event(make_event, m, method=method)
    create_subscription_case(db, event=ev)
    assert _the_case(db, m).context["mandate_type"] == expected.value


def test_missing_method_maps_to_nach(db, make_merchant, make_event):
    m = make_merchant()
    body = _payload(event="subscription.charged.failed")
    body["payload"]["payment"]["entity"].pop("method", None)
    ev = make_event(m, type="subscription.charged.failed", raw_payload=body)
    create_subscription_case(db, event=ev)
    assert _the_case(db, m).context["mandate_type"] == MandateType.NACH.value


def test_billing_cycle_derived_from_paid_count(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, paid_count=0)
    create_subscription_case(db, event=ev)
    assert _the_case(db, m).context["billing_cycle"] == "1"


def test_context_passes_the_typed_guard(db, make_merchant, make_event):
    # If the SubscriptionFailureContext were malformed this would raise on flush.
    m = make_merchant()
    ev = _event(make_event, m)
    create_subscription_case(db, event=ev)
    assert _the_case(db, m).context["mandate_id"]  # non-empty


def test_no_cross_leg_dedup_for_subscription(
    db, make_merchant, make_counterparty, make_case, make_event
):
    # A subscription failure never supersedes a CHECKOUT_ABANDONMENT case.
    m, cp = make_merchant(), make_counterparty()
    aband = make_case(
        merchant=m,
        counterparty=cp,
        leg=LegType.CHECKOUT_ABANDONMENT,
        context={
            "cart_id": "sub_M8001",
            "cart_value": "499.00",
            "drop_stage": "vpa_entry",
            "payment_method_attempted": "UPI_COLLECT",
        },
    )
    ev = _event(make_event, m, contact=cp.phone)
    create_subscription_case(db, event=ev)
    db.refresh(aband)
    assert aband.superseded_by_case_id is None
