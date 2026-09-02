"""Milestone 7a — the Razorpay webhook endpoint (Blueprint Module 2 §2.2).

Covers the verify-before-parse pipeline end to end: signature verification over
the raw bytes, silent HTTP-200 drop on any failure with zero side effects,
idempotency on `X-Razorpay-Event-Id`, per-merchant path attribution, and
live/test secret selection that never crosses the two.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from tests.conftest import WEBHOOK_LIVE_SECRET, WEBHOOK_TEST_SECRET
from torque.models import CaseEvent, Event, RevenueLeakCase
from torque.security.razorpay_signature import compute_razorpay_signature

SIG = "X-Razorpay-Signature"
EVID = "X-Razorpay-Event-Id"


def _body(event: str = "payment.failed", **extra) -> bytes:
    payload = {
        "entity": "event",
        "account_id": "acc_RZP123",
        "event": event,
        "contains": ["payment"],
        "payload": {"payment": {"entity": {"id": "pay_abc123", "amount": 49900}}},
        "created_at": 1_760_000_000,
    }
    payload.update(extra)
    return json.dumps(payload).encode()


def _headers(raw: bytes, secret: str, event_id: str | None = "evt_0001") -> dict[str, str]:
    h = {SIG: compute_razorpay_signature(raw, secret), "Content-Type": "application/json"}
    if event_id is not None:
        h[EVID] = event_id
    return h


def _post(client, merchant_id, raw, headers):
    return client.post(f"/webhooks/razorpay/{merchant_id}", content=raw, headers=headers)


def _events(db, merchant_id: str | None = None) -> list[Event]:
    stmt = select(Event)
    if merchant_id is not None:
        stmt = stmt.where(Event.merchant_id == merchant_id)
    return list(db.scalars(stmt))


# --- health -------------------------------------------------------------------


def test_health_ok(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- happy path -------------------------------------------------------------


def test_valid_signature_new_event_persists(api_client, db, make_merchant):
    m = make_merchant()
    raw = _body()
    resp = _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    assert resp.status_code == 200
    assert resp.content == b""

    rows = _events(db, m.merchant_id)
    assert len(rows) == 1
    ev = rows[0]
    assert ev.type == "payment.failed"
    assert ev.idempotency_key == "evt_0001"
    assert ev.raw_payload == json.loads(raw)
    assert ev.processed is False
    assert ev.merchant_id == m.merchant_id


def test_event_merchant_id_is_taken_from_the_path(api_client, db, make_merchant):
    m1 = make_merchant()
    m2 = make_merchant()
    raw = _body()
    _post(api_client, m2.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    assert _events(db, m1.merchant_id) == []
    assert len(_events(db, m2.merchant_id)) == 1


def test_raw_payload_stored_verbatim_as_parsed(api_client, db, make_merchant):
    m = make_merchant()
    raw = _body(event="subscription.charged.failed")
    _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    (ev,) = _events(db, m.merchant_id)
    assert ev.raw_payload == json.loads(raw)
    assert ev.type == "subscription.charged.failed"


# --- signature verification (fail-closed, no side effects) ------------------


def test_wrong_secret_drops_silently(api_client, db, make_merchant):
    m = make_merchant()
    raw = _body()
    resp = _post(api_client, m.merchant_id, raw, _headers(raw, "whsec_not_the_secret"))
    assert resp.status_code == 200
    assert _events(db) == []
    assert list(db.scalars(select(CaseEvent))) == []
    assert list(db.scalars(select(RevenueLeakCase))) == []


def test_missing_signature_header_drops(api_client, db, make_merchant):
    m = make_merchant()
    raw = _body()
    resp = _post(
        api_client, m.merchant_id, raw, {EVID: "evt_0001", "Content-Type": "application/json"}
    )
    assert resp.status_code == 200
    assert _events(db) == []


def test_body_tampered_after_signing_fails(api_client, db, make_merchant):
    m = make_merchant()
    signed = _body()
    sent = signed + b" "  # one extra byte — HMAC is over the exact bytes
    resp = _post(api_client, m.merchant_id, sent, _headers(signed, WEBHOOK_TEST_SECRET))
    assert resp.status_code == 200
    assert _events(db) == []


def test_reserialized_json_does_not_match(api_client, db, make_merchant):
    m = make_merchant()
    obj = json.loads(_body())
    compact = json.dumps(obj, separators=(",", ":")).encode()
    pretty = json.dumps(obj, indent=2).encode()  # same object, different bytes
    resp = _post(api_client, m.merchant_id, pretty, _headers(compact, WEBHOOK_TEST_SECRET))
    assert resp.status_code == 200
    assert _events(db) == []


def test_non_json_body_with_valid_signature_drops(api_client, db, make_merchant):
    m = make_merchant()
    raw = b"this is not json"
    resp = _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    assert resp.status_code == 200
    assert _events(db) == []


def test_json_but_not_an_object_drops(api_client, db, make_merchant):
    m = make_merchant()
    raw = b"[1, 2, 3]"
    resp = _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    assert resp.status_code == 200
    assert _events(db) == []


# --- idempotency ----------------------------------------------------------


def test_duplicate_event_id_is_not_reprocessed(api_client, db, make_merchant):
    m = make_merchant()
    raw = _body()
    hdrs = _headers(raw, WEBHOOK_TEST_SECRET, event_id="evt_dup")
    r1 = _post(api_client, m.merchant_id, raw, hdrs)
    r2 = _post(api_client, m.merchant_id, raw, hdrs)
    assert (r1.status_code, r2.status_code) == (200, 200)
    assert len(_events(db, m.merchant_id)) == 1


def test_distinct_event_ids_same_payload_both_persist(api_client, db, make_merchant):
    m = make_merchant()
    raw = _body()
    _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET, event_id="evt_a"))
    _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET, event_id="evt_b"))
    keys = {e.idempotency_key for e in _events(db, m.merchant_id)}
    assert keys == {"evt_a", "evt_b"}


def test_missing_event_id_header_drops(api_client, db, make_merchant):
    m = make_merchant()
    raw = _body()
    resp = _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET, event_id=None))
    assert resp.status_code == 200
    assert _events(db) == []


# --- event type handling -------------------------------------------------


def test_unrecognized_but_verified_event_type_is_persisted(api_client, db, make_merchant):
    m = make_merchant()
    raw = _body(event="beta.feature.something")
    _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    (ev,) = _events(db, m.merchant_id)
    assert ev.type == "beta.feature.something"


def test_body_without_event_field_persists_as_unknown(api_client, db, make_merchant):
    m = make_merchant()
    raw = json.dumps({"entity": "event", "payload": {}}).encode()
    _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    (ev,) = _events(db, m.merchant_id)
    assert ev.type == "unknown"


# --- merchant resolution -----------------------------------------------


def test_unknown_merchant_in_path_drops_silently(api_client, db):
    raw = _body()
    resp = _post(api_client, "acc_does_not_exist", raw, _headers(raw, WEBHOOK_TEST_SECRET))
    assert resp.status_code == 200
    assert _events(db) == []


def test_route_requires_a_merchant_id_segment(api_client):
    raw = _body()
    resp = api_client.post(
        "/webhooks/razorpay", content=raw, headers=_headers(raw, WEBHOOK_TEST_SECRET)
    )
    assert resp.status_code == 404


# --- live / test secret selection (never crossed) ---------------------------


def test_test_mode_verifies_against_test_secret_only(make_api_client, db, make_merchant):
    m = make_merchant()
    client = make_api_client(mode="test")
    raw = _body()

    good = _post(client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    assert good.status_code == 200
    assert len(_events(db, m.merchant_id)) == 1

    crossed = _post(
        client, m.merchant_id, raw, _headers(raw, WEBHOOK_LIVE_SECRET, event_id="evt_live_sig")
    )
    assert crossed.status_code == 200
    assert len(_events(db, m.merchant_id)) == 1  # unchanged — live sig rejected in test mode


def test_live_mode_verifies_against_live_secret_only(make_api_client, db, make_merchant):
    m = make_merchant()
    client = make_api_client(mode="live")
    raw = _body()

    crossed = _post(
        client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET, event_id="evt_test_sig")
    )
    assert crossed.status_code == 200
    assert _events(db, m.merchant_id) == []

    good = _post(
        client, m.merchant_id, raw, _headers(raw, WEBHOOK_LIVE_SECRET, event_id="evt_live_ok")
    )
    assert good.status_code == 200
    assert len(_events(db, m.merchant_id)) == 1


def test_unset_secret_for_the_mode_drops_everything(make_api_client, db, make_merchant):
    m = make_merchant()
    client = make_api_client(mode="test", with_secrets=False)
    raw = _body()
    resp = _post(client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    assert resp.status_code == 200
    assert _events(db) == []


# --- no side effects on a verified write beyond the Event row --------------


def test_successful_ingest_writes_no_case_or_case_event(api_client, db, make_merchant):
    m = make_merchant()
    raw = _body()
    _post(api_client, m.merchant_id, raw, _headers(raw, WEBHOOK_TEST_SECRET))
    assert len(_events(db, m.merchant_id)) == 1
    assert list(db.scalars(select(RevenueLeakCase))) == []
    assert list(db.scalars(select(CaseEvent))) == []
