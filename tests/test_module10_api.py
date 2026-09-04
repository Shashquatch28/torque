"""Module 10 — the HTTP surface: the Module 10 read endpoints, the Agent Console
write endpoints, and the Demo Surface controls. Uses the ingestion TestClient
fixture (its `get_db` override is the harness session)."""

from __future__ import annotations

from decimal import Decimal

from torque.coordination import human_queue as HQ
from torque.enums import CaseStatus, LegType


def _escalated(make_case, m, amount="9000.00"):
    return make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                     context={"gateway": "razorpay"}, amount_at_risk=Decimal(amount),
                     status=CaseStatus.ESCALATED_TO_HUMAN)


def test_read_endpoints(make_api_client, db, make_merchant, make_case):
    m = make_merchant()
    c = _escalated(make_case, m)
    HQ.enqueue(db, case=c, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
    from torque.scoring.score import score_case
    score_case(db, c)
    client = make_api_client()
    mid = m.merchant_id

    top = client.get(f"/reports/{mid}/top-at-risk?limit=5")
    assert top.status_code == 200
    assert top.json()["items"][0]["case_id"] == str(c.case_id)

    hq = client.get(f"/reports/{mid}/human-queue")
    assert hq.status_code == 200 and len(hq.json()["items"]) == 1
    assert hq.json()["items"][0]["reason"] == "LOW_CONFIDENCE_DIAGNOSIS"

    act = client.get(f"/reports/{mid}/activity")
    assert act.status_code == 200

    cd = client.get(f"/reports/{mid}/cases/{c.case_id}")
    assert cd.status_code == 200
    assert cd.json()["recovery_score_breakdown"] is not None

    assert client.get(f"/reports/{mid}/top-at-risk").status_code == 200
    assert client.get("/reports/nobody/top-at-risk").status_code == 404


def test_agent_console_resolve_endpoint(make_api_client, db, make_merchant, make_case):
    m = make_merchant()
    c = _escalated(make_case, m, amount="15000.00")
    HQ.enqueue(db, case=c, reason=HQ.HumanQueueReason.ESCALATION_CEILING)
    client = make_api_client()
    mid = m.merchant_id

    r = client.post(f"/agent-console/{mid}/cases/{c.case_id}/resolve",
                    json={"resolution": "RECOVERED_BY_HUMAN", "agent_id": "agent-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["from_status"] == "ESCALATED_TO_HUMAN"
    assert body["to_status"] == "RECOVERED"
    assert Decimal(str(body["recovered_amount"])) == Decimal("15000.00")

    # the dashboard reflects it immediately
    s = client.get(f"/reports/{mid}/summary").json()
    assert Decimal(str(s["recovered_amount"])) == Decimal("15000.00")

    # a second resolve on the now-terminal case → 409
    again = client.post(f"/agent-console/{mid}/cases/{c.case_id}/resolve",
                        json={"resolution": "WRITTEN_OFF", "agent_id": "agent-1"})
    assert again.status_code == 409


def test_agent_console_validation(make_api_client, db, make_merchant, make_case):
    m = make_merchant()
    c = _escalated(make_case, m)
    client = make_api_client()
    mid = m.merchant_id
    # bad resolution value → 422
    assert client.post(f"/agent-console/{mid}/cases/{c.case_id}/resolve",
                       json={"resolution": "NONSENSE", "agent_id": "a"}).status_code == 422
    # missing agent_id → 422 (pydantic min_length)
    assert client.post(f"/agent-console/{mid}/cases/{c.case_id}/resolve",
                       json={"resolution": "WRITTEN_OFF"}).status_code == 422
    # unknown merchant → 404
    assert client.post(f"/agent-console/nobody/cases/{c.case_id}/resolve",
                       json={"resolution": "WRITTEN_OFF", "agent_id": "a"}).status_code == 404
    # pause a non-PLAYBOOK_ACTIVE case → 409
    assert client.post(f"/agent-console/{mid}/cases/{c.case_id}/pause",
                       json={"agent_id": "a"}).status_code == 409


def test_pause_unpause_endpoints(make_api_client, db, make_merchant, make_case):
    m = make_merchant()
    c = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                  context={"gateway": "razorpay"}, amount_at_risk=Decimal("2000.00"),
                  status=CaseStatus.PLAYBOOK_ACTIVE)
    client = make_api_client()
    mid = m.merchant_id
    assert client.post(f"/agent-console/{mid}/cases/{c.case_id}/pause",
                       json={"agent_id": "a"}).json()["to_status"] == "PAUSED"
    assert client.post(f"/agent-console/{mid}/cases/{c.case_id}/unpause",
                       json={"agent_id": "a"}).json()["to_status"] == "PLAYBOOK_ACTIVE"


def test_demo_endpoints(make_api_client):
    client = make_api_client()
    dm = client.get("/demo/merchant").json()
    assert dm["merchant_id"] == "acc_demo"

    seeded = client.post("/demo/seed").json()
    assert seeded["seeded"] is True and seeded["case_count"] >= 15

    scen = client.get("/demo/scenarios").json()
    assert {s["key"] for s in scen} >= {
        "checkout_abandonment", "hard_stop_mac", "upi_retry_cap", "nach_ceiling",
    }

    inj = client.post("/demo/inject/hard_stop_mac")
    assert inj.status_code == 200
    assert inj.json()["block_reason"] == "NETWORK_HARD_STOP"

    assert client.post("/demo/inject/bogus").status_code == 404

    # after seeding + injecting, the exception list is non-empty
    exc = client.get("/reports/acc_demo/exceptions").json()
    assert exc["blocked_by_reason"]


def test_demo_inject_requires_seed(make_api_client, db):
    # fresh harness DB: no acc_demo merchant yet
    client = make_api_client()
    r = client.post("/demo/inject/payment_failure")
    assert r.status_code == 409
