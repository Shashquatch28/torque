"""Module 9 §9.9 — hard tenant-isolation requirement. Merchant A must never see
merchant B's cases, recovered revenue, actions, exceptions, or event streams —
through any metrics function or any HTTP endpoint.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.module9_helpers import add_action, set_recovery, set_status
from torque.enums import ActionOutcome, BlockReason, CaseStatus, LegType, RecoveryType
from torque.reporting import metrics

_A = RecoveryType.AGENT_ASSISTED


@pytest.fixture()
def two_merchants(db, make_merchant, make_case):
    """Merchant A: 1 recovered ₹10,000 + 1 blocked + 1 escalated.
    Merchant B: 1 recovered ₹99,999 + its own blocked/escalated."""
    from torque.coordination import human_queue as HQ

    a, b = make_merchant(), make_merchant()

    def _seed(m, recovered_amount):
        rec = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                        context={"gateway": "razorpay"},
                        amount_at_risk=Decimal(str(recovered_amount)))
        set_recovery(db, rec, recovery_type=_A, amount=str(recovered_amount))
        blk = make_case(merchant=m, leg=LegType.SUBSCRIPTION_FAILURE,
                        amount_at_risk=Decimal("1234.00"),
                        context={"mandate_id": "x", "mandate_type": "CARD",
                                 "billing_cycle": "1", "subscription_id": "s"})
        add_action(db, blk, outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
                   block_reason=BlockReason.NETWORK_HARD_STOP)
        esc = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                        context={"gateway": "razorpay"}, amount_at_risk=Decimal("500.00"),
                        status=CaseStatus.ESCALATED_TO_HUMAN)
        HQ.enqueue(db, case=esc, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
        return rec, blk, esc

    a_rows = _seed(a, "10000.00")
    b_rows = _seed(b, "99999.00")
    return a, b, a_rows, b_rows


def test_summary_is_tenant_scoped(two_merchants, db):
    a, b, _, _ = two_merchants
    sa = metrics.recovery_summary(db, a.merchant_id)
    sb = metrics.recovery_summary(db, b.merchant_id)
    assert sa.case_count == 3 and sb.case_count == 3
    assert sa.recovered_amount == Decimal("10000.00")
    assert sb.recovered_amount == Decimal("99999.00")
    # A's total revenue at risk never includes B's ₹99,999
    assert sa.revenue_at_risk == Decimal("11734.00")


def test_by_leg_and_by_type_are_tenant_scoped(two_merchants, db):
    a, b, _, _ = two_merchants
    a_legs = {r.leg_type: r for r in metrics.recovery_by_leg(db, a.merchant_id)}
    assert a_legs["PAYMENT_DEGRADATION"].recovered_amount == Decimal("10000.00")
    a_types = {r.recovery_type: r for r in metrics.recovery_by_recovery_type(db, a.merchant_id)}
    assert a_types["AGENT_ASSISTED"].recovered_amount == Decimal("10000.00")


def test_over_time_is_tenant_scoped(two_merchants, db):
    a, b, _, _ = two_merchants
    ta = metrics.recovery_over_time(db, a.merchant_id)
    assert sum(x.recovered_amount for x in ta) == Decimal("10000.00")


def test_operational_report_is_tenant_scoped(two_merchants, db):
    a, b, _, _ = two_merchants
    ra = metrics.operational_exceptions(db, a.merchant_id)
    assert ra.escalated_case_count == 1
    assert sum(x.action_count for x in ra.blocked_by_reason) == 1
    assert sum(t.case_count for t in ra.terminal_by_status) == 1  # only A's recovered


def test_list_cases_is_tenant_scoped(two_merchants, db):
    a, b, _, _ = two_merchants
    la = metrics.list_cases(db, a.merchant_id)
    assert la.total == 3
    assert all(item.case_id for item in la.items)
    b_ids = {str(c.case_id) for c in two_merchants[3]}
    assert not ({item.case_id for item in la.items} & b_ids)


def test_case_detail_and_events_refuse_cross_tenant(two_merchants, db):
    a, b, a_rows, b_rows = two_merchants
    b_case = b_rows[0]
    # A asking for B's case → None (404 at the API layer)
    assert metrics.case_detail(db, a.merchant_id, b_case.case_id) is None
    assert metrics.case_event_stream(db, a.merchant_id, b_case.case_id) is None
    # B can see its own
    assert metrics.case_detail(db, b.merchant_id, b_case.case_id) is not None


def test_batch_window_cannot_cross_tenants(two_merchants, db, make_case):
    a, b, _, _ = two_merchants
    from datetime import UTC, datetime

    from torque.reporting.metrics import ReportWindow

    win = ReportWindow(start=datetime(2000, 1, 1, tzinfo=UTC))
    sa = metrics.recovery_summary(db, a.merchant_id, window=win)
    assert sa.recovered_amount == Decimal("10000.00")  # never B's


# --- HTTP layer -----------------------------------------------------


def test_api_endpoints_are_tenant_scoped(two_merchants, db, make_api_client):
    a, b, a_rows, b_rows = two_merchants
    client = make_api_client()

    ra = client.get(f"/reports/{a.merchant_id}/summary")
    assert ra.status_code == 200
    assert Decimal(str(ra.json()["recovered_amount"])) == Decimal("10000.00")

    rb = client.get(f"/reports/{b.merchant_id}/summary")
    assert Decimal(str(rb.json()["recovered_amount"])) == Decimal("99999.00")

    # A cannot drill into B's case
    r = client.get(f"/reports/{a.merchant_id}/cases/{b_rows[0].case_id}")
    assert r.status_code == 404
    r2 = client.get(f"/reports/{a.merchant_id}/cases/{b_rows[0].case_id}/events")
    assert r2.status_code == 404

    # A's case list never contains B's ids
    cases = client.get(f"/reports/{a.merchant_id}/cases").json()
    b_ids = {str(c.case_id) for c in b_rows}
    assert not ({i["case_id"] for i in cases["items"]} & b_ids)


def test_api_unknown_merchant_is_404(db, make_api_client):
    client = make_api_client()
    assert client.get("/reports/nobody/summary").status_code == 404
    assert client.get("/reports/nobody/report").status_code == 404
    assert client.get("/reports/nobody/exceptions").status_code == 404


def test_metrics_reject_empty_merchant_id(db):
    from torque.exceptions import TenantScopeError

    with pytest.raises(TenantScopeError):
        metrics.recovery_summary(db, "")


def test_status_helper_used(db, make_merchant, make_case):
    # keep set_status import meaningful for the isolation dataset variants
    m = make_merchant()
    c = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                  context={"gateway": "razorpay"}, amount_at_risk=Decimal("1.00"))
    set_status(db, c, CaseStatus.EXHAUSTED)
    assert metrics.recovery_summary(db, m.merchant_id).exhausted_case_count == 1
