"""Milestone 8 — the webhook's dispatch of `subscription.charged.failed` to the 30 s buffer task."""

from __future__ import annotations

import json

from sqlalchemy import select

from tests.conftest import WEBHOOK_TEST_SECRET, razorpay_payment_body, razorpay_subscription_body
from torque.models import Event
from torque.security.razorpay_signature import compute_razorpay_signature

SIG = "X-Razorpay-Signature"
EVID = "X-Razorpay-Event-Id"


def _headers(raw: bytes, event_id: str) -> dict[str, str]:
    return {
        SIG: compute_razorpay_signature(raw, WEBHOOK_TEST_SECRET),
        EVID: event_id,
        "Content-Type": "application/json",
    }


def _events(db, mid):
    return list(db.scalars(select(Event).where(Event.merchant_id == mid)))


def test_subscription_failed_enqueues_the_30s_buffer_task(api_client, db, make_merchant):
    m = make_merchant()
    raw = razorpay_subscription_body(event="subscription.charged.failed")
    r = api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_sf_1")
    )
    assert r.status_code == 200
    (ev,) = _events(db, m.merchant_id)
    api_client.subscription_enqueue.assert_called_once()
    args, kwargs = api_client.subscription_enqueue.call_args
    assert args[0] == (str(ev.event_id),)
    assert kwargs["countdown"] == 30
    api_client.buffer_enqueue.assert_not_called()


def test_subscription_charged_success_does_not_enqueue(api_client, db, make_merchant):
    m = make_merchant()
    raw = razorpay_subscription_body(event="subscription.charged")
    api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_sc_1")
    )
    assert len(_events(db, m.merchant_id)) == 1
    api_client.subscription_enqueue.assert_not_called()


def test_duplicate_subscription_failed_enqueues_once(api_client, db, make_merchant):
    m = make_merchant()
    raw = razorpay_subscription_body(event="subscription.charged.failed")
    h = _headers(raw, "evt_sf_dup")
    api_client.post(f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=h)
    api_client.post(f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=h)
    assert len(_events(db, m.merchant_id)) == 1
    api_client.subscription_enqueue.assert_called_once()


def test_payment_failed_still_routes_to_the_payment_task(api_client, db, make_merchant):
    m = make_merchant()
    raw = razorpay_payment_body(event="payment.failed")
    api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_pf_reg")
    )
    api_client.buffer_enqueue.assert_called_once()
    api_client.subscription_enqueue.assert_not_called()


def test_composed_end_to_end_subscription_failure_creates_case(api_client, db, make_merchant):
    from torque.enums import LegType
    from torque.ingestion.subscription import resolve_subscription_buffered_event
    from torque.models import RevenueLeakCase

    m = make_merchant()
    raw = razorpay_subscription_body(event="subscription.charged.failed")
    api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_e2e_sf")
    )
    (ev,) = _events(db, m.merchant_id)
    resolve_subscription_buffered_event(db, event_id=ev.event_id)
    cases = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).all()
    assert len(cases) == 1 and cases[0].leg_type is LegType.SUBSCRIPTION_FAILURE
    assert json.loads(raw)  # body was well-formed
