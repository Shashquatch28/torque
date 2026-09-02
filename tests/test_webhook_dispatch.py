"""Milestone 7b — the webhook's post-`Event` dispatch to the buffer task."""

from __future__ import annotations

import json
from contextlib import contextmanager

from sqlalchemy import select

from tests.conftest import WEBHOOK_TEST_SECRET, razorpay_payment_body
from torque.ingestion.buffer import resolve_buffered_event
from torque.models import Event, RevenueLeakCase
from torque.security.razorpay_signature import compute_razorpay_signature

SIG = "X-Razorpay-Signature"
EVID = "X-Razorpay-Event-Id"


def _headers(raw: bytes, event_id: str, secret: str = WEBHOOK_TEST_SECRET) -> dict[str, str]:
    return {
        SIG: compute_razorpay_signature(raw, secret),
        EVID: event_id,
        "Content-Type": "application/json",
    }


def _events(db, merchant_id):
    return list(db.scalars(select(Event).where(Event.merchant_id == merchant_id)))


def test_payment_failed_enqueues_the_buffer_task(api_client, db, make_merchant):
    m = make_merchant()
    raw = razorpay_payment_body(event="payment.failed")
    r = api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_pf_1")
    )
    assert r.status_code == 200
    (ev,) = _events(db, m.merchant_id)
    api_client.buffer_enqueue.assert_called_once()
    args, kwargs = api_client.buffer_enqueue.call_args
    assert args[0] == (str(ev.event_id),)
    assert kwargs["countdown"] == 90


def test_payment_captured_does_not_enqueue(api_client, db, make_merchant):
    m = make_merchant()
    raw = razorpay_payment_body(event="payment.captured")
    r = api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_pc_1")
    )
    assert r.status_code == 200
    assert len(_events(db, m.merchant_id)) == 1
    api_client.buffer_enqueue.assert_not_called()


def test_non_payment_event_does_not_enqueue(api_client, db, make_merchant):
    m = make_merchant()
    raw = json.dumps({"event": "invoice.overdue", "payload": {}}).encode()
    api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_io_1")
    )
    assert len(_events(db, m.merchant_id)) == 1
    api_client.buffer_enqueue.assert_not_called()


def test_duplicate_payment_failed_enqueues_once(api_client, db, make_merchant):
    m = make_merchant()
    raw = razorpay_payment_body(event="payment.failed")
    h = _headers(raw, "evt_dup_1")
    api_client.post(f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=h)
    api_client.post(f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=h)
    assert len(_events(db, m.merchant_id)) == 1
    api_client.buffer_enqueue.assert_called_once()


def test_composed_end_to_end_failed_then_buffer_creates_case(api_client, db, make_merchant):
    m = make_merchant()
    raw = razorpay_payment_body(event="payment.failed")
    api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_e2e_1")
    )
    (ev,) = _events(db, m.merchant_id)
    # run what the Celery task would run, against the same session
    resolve_buffered_event(db, event_id=ev.event_id)
    cases = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).all()
    assert len(cases) == 1
    assert cases[0].source_event_id == ev.event_id


def test_eager_task_runs_inline_and_creates_case(
    make_api_client, db, make_merchant, celery_eager, monkeypatch
):
    @contextmanager
    def _fake_scope():
        yield db

    monkeypatch.setattr("torque.ingestion.tasks._session_scope", _fake_scope)
    client = make_api_client(patch_enqueue=False)

    m = make_merchant()
    raw = razorpay_payment_body(event="payment.failed")
    r = client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_eager_1")
    )
    assert r.status_code == 200
    cases = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).all()
    assert len(cases) == 1
