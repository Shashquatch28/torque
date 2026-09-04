"""Module 9 §9.10 — the read-only HTTP surface. All six UI asks: merchant
summary, batch summary, by-intervention, over-time, case drill-down, operational
exceptions — plus the explainability stream and parameter validation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.module9_helpers import add_action, set_recovery
from torque.enums import ActionOutcome, ActionType, BlockReason, LegType, RecoveryType

_A = RecoveryType.AGENT_ASSISTED


@pytest.fixture()
def seeded(db, make_merchant, make_case, make_api_client):
    m = make_merchant()
    rec = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                    context={"gateway": "razorpay"}, amount_at_risk=Decimal("12400.00"))
    add_action(db, rec, action_type=ActionType.SEND_WHATSAPP, cost="0.885")
    set_recovery(db, rec, recovery_type=_A, amount="12400.00",
                 closed_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC))
    blk = make_case(merchant=m, leg=LegType.CHECKOUT_ABANDONMENT, amount_at_risk=Decimal("900.00"),
                    context={"cart_id": "c", "cart_value": "900.00",
                             "drop_stage": "review", "payment_method_attempted": "NONE"})
    add_action(db, blk, outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
               block_reason=BlockReason.CONSENT_NOT_OBTAINED)
    return m, rec, blk, make_api_client()


def test_summary_endpoint(seeded):
    m, rec, blk, client = seeded
    r = client.get(f"/reports/{m.merchant_id}/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["case_count"] == 2
    assert Decimal(str(body["revenue_at_risk"])) == Decimal("13300.00")
    assert Decimal(str(body["recovered_amount"])) == Decimal("12400.00")
    assert Decimal(str(body["blocked_amount"])) == Decimal("900.00")
    assert body["recovered_case_count"] == 1


def test_report_bundle_endpoint(seeded):
    m, *_rest, client = seeded
    body = client.get(f"/reports/{m.merchant_id}/report").json()
    assert set(body) == {"summary", "by_leg", "by_recovery_type", "operational"}
    legs = {r["leg_type"]: r for r in body["by_leg"]}
    assert Decimal(str(legs["PAYMENT_DEGRADATION"]["recovered_amount"])) == Decimal("12400.00")
    assert legs["CHECKOUT_ABANDONMENT"]["cases_recovered"] == 0
    assert body["operational"]["blocked_by_reason"][0]["block_reason"] == "CONSENT_NOT_OBTAINED"


def test_by_intervention_endpoint_leg_and_action_type(seeded):
    m, *_rest, client = seeded
    by_leg = client.get(f"/reports/{m.merchant_id}/by-intervention").json()
    assert {r["leg_type"] for r in by_leg} == {"PAYMENT_DEGRADATION", "CHECKOUT_ABANDONMENT"}

    by_action = client.get(
        f"/reports/{m.merchant_id}/by-intervention", params={"by": "action_type"}
    ).json()
    types = {r["action_type"]: r for r in by_action}
    # only executed actions count as "attempted"; the blocked one is excluded
    assert "SEND_WHATSAPP" in types
    assert types["SEND_WHATSAPP"]["cases_recovered"] == 1


def test_over_time_endpoint(seeded):
    m, *_rest, client = seeded
    rows = client.get(
        f"/reports/{m.merchant_id}/over-time", params={"bucket": "day"}
    ).json()
    assert len(rows) == 1
    assert Decimal(str(rows[0]["recovered_amount"])) == Decimal("12400.00")
    assert rows[0]["bucket"] == "day"


def test_over_time_rejects_bad_bucket(seeded):
    m, *_rest, client = seeded
    r = client.get(f"/reports/{m.merchant_id}/over-time", params={"bucket": "year"})
    assert r.status_code == 422  # FastAPI Literal validation


def test_exceptions_endpoint(seeded):
    m, *_rest, client = seeded
    body = client.get(f"/reports/{m.merchant_id}/exceptions").json()
    assert body["blocked_by_reason"][0]["case_count"] == 1
    assert body["deferred_action_count"] == 0


def test_cases_list_and_pagination(seeded):
    m, rec, blk, client = seeded
    body = client.get(f"/reports/{m.merchant_id}/cases").json()
    assert body["total"] == 2
    assert len(body["items"]) == 2

    page = client.get(
        f"/reports/{m.merchant_id}/cases", params={"limit": 1, "offset": 0}
    ).json()
    assert page["total"] == 2 and len(page["items"]) == 1

    filtered = client.get(
        f"/reports/{m.merchant_id}/cases", params={"leg": "PAYMENT_DEGRADATION"}
    ).json()
    assert [i["case_id"] for i in filtered["items"]] == [str(rec.case_id)]


def test_case_detail_endpoint(seeded):
    m, rec, blk, client = seeded
    body = client.get(f"/reports/{m.merchant_id}/cases/{rec.case_id}").json()
    assert body["recovery_type"] == "AGENT_ASSISTED"
    assert Decimal(str(body["recovered_amount"])) == Decimal("12400.00")
    assert Decimal(str(body["revenue_at_risk"])) == Decimal("12400.00")
    assert body["is_terminal"] is True
    assert body["actions"][0]["action_type"] == "SEND_WHATSAPP"
    assert Decimal(str(body["actions"][0]["cost"])) == Decimal("0.8850")


def test_case_events_explainability_stream(seeded):
    m, rec, blk, client = seeded
    events = client.get(f"/reports/{m.merchant_id}/cases/{rec.case_id}/events").json()
    seqs = [e["event_seq_id"] for e in events]
    assert seqs == sorted(seqs)  # event_seq_id order
    types = {e["event_type"] for e in events}
    assert "PAYMENT_RECONCILED" in types or "ACTION_EXECUTED" in types
    want = {"event_seq_id", "event_type", "actor", "timestamp", "reasoning", "payload"}
    for e in events:
        assert set(e) == want


def test_case_detail_unknown_case_is_404(seeded):
    import uuid

    m, *_rest, client = seeded
    r = client.get(f"/reports/{m.merchant_id}/cases/{uuid.uuid4()}")
    assert r.status_code == 404


def test_bad_leg_filter_is_422(seeded):
    m, *_rest, client = seeded
    assert client.get(
        f"/reports/{m.merchant_id}/summary", params={"leg": "NONSENSE"}
    ).status_code == 422


def test_batch_window_query_params(seeded):
    m, rec, blk, client = seeded
    empty = client.get(
        f"/reports/{m.merchant_id}/summary",
        params={"opened_from": "2099-01-01T00:00:00Z"},
    ).json()
    assert empty["case_count"] == 0
