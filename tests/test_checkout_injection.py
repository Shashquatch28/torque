"""Module 2 Leg 2 — the signed synthetic `checkout.abandoned` injection endpoint
(`POST /internal/checkout-abandoned/{merchant_id}`, Blueprint §2.6)."""

from __future__ import annotations

import json

from sqlalchemy import select

from tests.conftest import CHECKOUT_INJECTION_SECRET, checkout_abandoned_body
from torque.models import Event
from torque.security.razorpay_signature import compute_razorpay_signature

SIG = "X-Torque-Signature"
EVID = "X-Torque-Event-Id"


def _headers(raw: bytes, event_id: str, secret: str = CHECKOUT_INJECTION_SECRET):
    h = {SIG: compute_razorpay_signature(raw, secret), "Content-Type": "application/json"}
    if event_id is not None:
        h[EVID] = event_id
    return h


def _post(client, merchant_id, raw, headers):
    return client.post(
        f"/internal/checkout-abandoned/{merchant_id}", content=raw, headers=headers
    )


def _events(db, merchant_id=None):
    stmt = select(Event)
    if merchant_id is not None:
        stmt = stmt.where(Event.merchant_id == merchant_id)
    return list(db.scalars(stmt))


def test_valid_signed_injection_persists_event_and_enqueues(api_client, db, make_merchant):
    m = make_merchant()
    raw = checkout_abandoned_body()
    r = _post(api_client, m.merchant_id, raw, _headers(raw, "evt_ck_1"))
    assert r.status_code == 200 and r.content == b""

    (ev,) = _events(db, m.merchant_id)
    assert ev.type == "checkout.abandoned"
    assert ev.idempotency_key == "evt_ck_1"
    assert ev.raw_payload == json.loads(raw)
    assert ev.processed is False
    api_client.checkout_enqueue.assert_called_once()
    args, _kw = api_client.checkout_enqueue.call_args
    assert args[0] == (str(ev.event_id),)


def test_bad_signature_drops_silently(api_client, db, make_merchant):
    m = make_merchant()
    raw = checkout_abandoned_body()
    r = _post(api_client, m.merchant_id, raw, _headers(raw, "evt_ck_x", secret="wrong"))
    assert r.status_code == 200
    assert _events(db) == []
    api_client.checkout_enqueue.assert_not_called()


def test_missing_signature_drops(api_client, db, make_merchant):
    m = make_merchant()
    raw = checkout_abandoned_body()
    h = {EVID: "evt_ck_2", "Content-Type": "application/json"}
    r = _post(api_client, m.merchant_id, raw, h)
    assert r.status_code == 200
    assert _events(db) == []


def test_tampered_body_fails(api_client, db, make_merchant):
    m = make_merchant()
    signed = checkout_abandoned_body()
    r = _post(api_client, m.merchant_id, signed + b" ", _headers(signed, "evt_ck_3"))
    assert r.status_code == 200
    assert _events(db) == []


def test_missing_event_id_drops(api_client, db, make_merchant):
    m = make_merchant()
    raw = checkout_abandoned_body()
    r = _post(api_client, m.merchant_id, raw, _headers(raw, None))
    assert r.status_code == 200
    assert _events(db) == []


def test_unknown_merchant_drops(api_client, db):
    raw = checkout_abandoned_body()
    r = _post(api_client, "acc_nope", raw, _headers(raw, "evt_ck_4"))
    assert r.status_code == 200
    assert _events(db) == []


def test_duplicate_event_id_not_reprocessed(api_client, db, make_merchant):
    m = make_merchant()
    raw = checkout_abandoned_body()
    h = _headers(raw, "evt_ck_dup")
    _post(api_client, m.merchant_id, raw, h)
    _post(api_client, m.merchant_id, raw, h)
    assert len(_events(db, m.merchant_id)) == 1
    api_client.checkout_enqueue.assert_called_once()


def test_unset_secret_fails_closed(make_api_client, db, make_merchant):
    m = make_merchant()
    client = make_api_client(with_secrets=False)
    raw = checkout_abandoned_body()
    r = _post(client, m.merchant_id, raw, _headers(raw, "evt_ck_5"))
    assert r.status_code == 200
    assert _events(db) == []


def test_non_json_body_drops(api_client, db, make_merchant):
    m = make_merchant()
    raw = b"not json"
    r = _post(api_client, m.merchant_id, raw, _headers(raw, "evt_ck_6"))
    assert r.status_code == 200
    assert _events(db) == []
