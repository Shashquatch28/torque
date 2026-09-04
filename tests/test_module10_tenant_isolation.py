"""Module 10 §10.12 — tenant isolation for every new surface. Merchant A must
never see or mutate merchant B's data through the top-at-risk list, the human
queue, the activity feed, case detail, or the Agent Console.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.module9_helpers import add_action
from torque.agent_console import EscalationResolution, resolve_escalation
from torque.coordination import human_queue as HQ
from torque.enums import CaseStatus, LegType
from torque.exceptions import CaseNotFoundError
from torque.reporting import (
    case_detail,
    case_event_stream,
    human_queue_list,
    recent_activity,
    top_at_risk_cases,
)
from torque.scoring.score import score_case


@pytest.fixture()
def two_tenants(db, make_merchant, make_case):
    a, b = make_merchant(), make_merchant()

    def _seed(m, amount):
        esc = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                        context={"gateway": "razorpay"}, amount_at_risk=Decimal(amount),
                        status=CaseStatus.ESCALATED_TO_HUMAN,
                        root_cause_code="ISSUER_SOFT_DECLINE_NSF", diagnosis_confidence=0.8)
        score_case(db, esc)
        HQ.enqueue(db, case=esc, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
        add_action(db, esc)
        return esc

    return a, b, _seed(a, "10000.00"), _seed(b, "99999.00")


def test_top_at_risk_is_scoped(two_tenants, db):
    a, b, ca, cb = two_tenants
    ids_a = {i.case_id for i in top_at_risk_cases(db, a.merchant_id).items}
    assert ids_a == {str(ca.case_id)}
    assert str(cb.case_id) not in ids_a


def test_human_queue_is_scoped(two_tenants, db):
    a, b, ca, cb = two_tenants
    qa = human_queue_list(db, a.merchant_id)
    assert [i.case_id for i in qa.items] == [str(ca.case_id)]
    assert all(i.amount_at_risk == Decimal("10000.00") for i in qa.items)


def test_activity_feed_is_scoped(two_tenants, db):
    a, b, ca, cb = two_tenants
    fa = recent_activity(db, a.merchant_id)
    assert fa.items and all(e.case_id == str(ca.case_id) for e in fa.items)


def test_case_detail_and_events_refuse_cross_tenant(two_tenants, db):
    a, b, ca, cb = two_tenants
    assert case_detail(db, a.merchant_id, cb.case_id) is None
    assert case_event_stream(db, a.merchant_id, cb.case_id) is None
    assert case_detail(db, b.merchant_id, cb.case_id) is not None


def test_agent_console_refuses_cross_tenant_case(two_tenants, db):
    a, b, ca, cb = two_tenants
    with pytest.raises(CaseNotFoundError):
        resolve_escalation(db, merchant_id=a.merchant_id, case_id=cb.case_id,
                           resolution=EscalationResolution.WRITTEN_OFF, agent_id="x")
    # b's case is untouched
    db.refresh(cb)
    assert cb.status is CaseStatus.ESCALATED_TO_HUMAN


def test_api_layer_is_scoped(two_tenants, make_api_client):
    a, b, ca, cb = two_tenants
    client = make_api_client()
    # A's top-at-risk never carries B's ₹99,999 case
    items = client.get(f"/reports/{a.merchant_id}/top-at-risk").json()["items"]
    assert {i["case_id"] for i in items} == {str(ca.case_id)}
    # A cannot resolve B's case
    r = client.post(f"/agent-console/{a.merchant_id}/cases/{cb.case_id}/resolve",
                    json={"resolution": "WRITTEN_OFF", "agent_id": "x"})
    assert r.status_code == 404
    # A cannot read B's case detail
    assert client.get(f"/reports/{a.merchant_id}/cases/{cb.case_id}").status_code == 404
