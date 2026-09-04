"""Module 9b — the `GET /reports/{merchant_id}/incrementality` endpoint.

Read-only, tenant-scoped, exact response schema. Same FastAPI conventions as the
rest of the Module 9 reporting router.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from tests.module9b_helpers import WINDOW_END, WINDOW_MID, WINDOW_START, cohort_case
from torque.models import Action, CaseEvent, MerchantCounterparty, RevenueLeakCase

INCR = "/reports/{m}/incrementality"


def _seed(make_case, m, *, t_rec, t_miss, c_rec, c_miss):
    for _ in range(t_rec):
        cohort_case(make_case, m, control=False, recovered=True)
    for _ in range(t_miss):
        cohort_case(make_case, m, control=False, recovered=False)
    for _ in range(c_rec):
        cohort_case(make_case, m, control=True, recovered=True)
    for _ in range(c_miss):
        cohort_case(make_case, m, control=True, recovered=False)


def test_successful_response_exact_schema(db, make_merchant, make_case, make_api_client):
    m = make_merchant()
    _seed(make_case, m, t_rec=6, t_miss=6, c_rec=1, c_miss=3)
    client = make_api_client()

    r = client.get(INCR.format(m=m.merchant_id))
    assert r.status_code == 200
    body = r.json()

    assert set(body) == {
        "merchant_id", "opened_from", "opened_to", "leg_type", "window_basis",
        "confidence_level", "z_value", "recovery_definition",
        "treatment", "control", "lift", "sutva",
    }
    assert body["merchant_id"] == m.merchant_id
    assert body["window_basis"] == "opened_at"
    assert body["confidence_level"] == "0.95"
    for arm in ("treatment", "control"):
        assert set(body[arm]) == {"successes", "total", "rate", "ci_low", "ci_high"}
    assert set(body["lift"]) == {"point", "ci_low", "ci_high", "method"}
    assert body["lift"]["method"] == "newcombe_wilson_hybrid_score"
    assert set(body["sutva"]) == {
        "contaminated_control_counterparties", "excluded_control_cases",
        "control", "lift", "note",
    }
    assert body["treatment"]["successes"] == 6 and body["treatment"]["total"] == 12
    assert body["treatment"]["rate"] == "0.5000"
    assert body["treatment"]["ci_low"] == "0.2538" and body["treatment"]["ci_high"] == "0.7462"
    assert body["control"]["rate"] == "0.2500"
    assert body["lift"]["point"] == "0.2500"


def test_empty_dataset_is_200_with_nulls(db, make_merchant, make_api_client):
    m = make_merchant()
    client = make_api_client()
    body = client.get(INCR.format(m=m.merchant_id)).json()
    assert body["treatment"] == {
        "successes": 0, "total": 0, "rate": None, "ci_low": None, "ci_high": None
    }
    assert body["lift"]["point"] is None
    assert body["sutva"]["contaminated_control_counterparties"] == 0


def test_unknown_merchant_404(db, make_api_client):
    client = make_api_client()
    assert client.get(INCR.format(m="acc_does_not_exist")).status_code == 404


def test_invalid_leg_422(db, make_merchant, make_api_client):
    m = make_merchant()
    client = make_api_client()
    r = client.get(INCR.format(m=m.merchant_id) + "?leg=NOT_A_LEG")
    assert r.status_code == 422


def test_invalid_window_value_422(db, make_merchant, make_api_client):
    m = make_merchant()
    client = make_api_client()
    r = client.get(INCR.format(m=m.merchant_id) + "?opened_from=not-a-date")
    assert r.status_code == 422


def test_window_params_echoed_and_applied(db, make_merchant, make_case, make_api_client):
    m = make_merchant()
    cohort_case(make_case, m, control=False, recovered=True, opened_at=WINDOW_MID)
    cohort_case(make_case, m, control=True, recovered=True, opened_at=WINDOW_MID)
    client = make_api_client()
    body = client.get(
        INCR.format(m=m.merchant_id),
        params={
            "opened_from": WINDOW_START.isoformat(),
            "opened_to": WINDOW_END.isoformat(),
        },
    ).json()
    assert body["opened_from"].startswith("2026-06-01")
    assert body["treatment"]["total"] == 1 and body["control"]["total"] == 1


def test_tenant_isolation_other_merchant_cohort_not_visible(
    db, make_merchant, make_case, make_api_client
):
    a, b = make_merchant(), make_merchant()
    _seed(make_case, a, t_rec=2, t_miss=0, c_rec=1, c_miss=1)
    _seed(make_case, b, t_rec=9, t_miss=0, c_rec=9, c_miss=0)  # b's numbers differ
    client = make_api_client()

    body_a = client.get(INCR.format(m=a.merchant_id)).json()
    assert body_a["treatment"]["total"] == 2   # only a's cases
    assert body_a["control"]["total"] == 2
    assert body_a["sutva"]["contaminated_control_counterparties"] == 0  # no shared cp


def test_endpoint_is_read_only(db, make_merchant, make_counterparty, make_case, make_api_client):
    m, other = make_merchant(), make_merchant()
    shared = make_counterparty()
    cohort_case(make_case, m, control=True, recovered=True, counterparty=shared)
    cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, other, control=False, recovered=True, counterparty=shared)
    client = make_api_client()

    def _counts():
        return {
            "cases": db.scalar(select(func.count()).select_from(RevenueLeakCase)),
            "events": db.scalar(select(func.count()).select_from(CaseEvent)),
            "actions": db.scalar(select(func.count()).select_from(Action)),
            "mc": db.scalar(select(func.count()).select_from(MerchantCounterparty)),
        }

    before = _counts()
    before_cg = dict(
        db.execute(
            select(RevenueLeakCase.case_id, RevenueLeakCase.control_group)
        ).all()
    )

    for _ in range(3):
        assert client.get(INCR.format(m=m.merchant_id)).status_code == 200

    assert _counts() == before
    after_cg = dict(
        db.execute(
            select(RevenueLeakCase.case_id, RevenueLeakCase.control_group)
        ).all()
    )
    assert after_cg == before_cg  # cohort assignments untouched


def test_repeated_calls_identical(db, make_merchant, make_case, make_api_client):
    m = make_merchant()
    _seed(make_case, m, t_rec=3, t_miss=2, c_rec=1, c_miss=2)
    client = make_api_client()
    a = client.get(INCR.format(m=m.merchant_id)).json()
    b = client.get(INCR.format(m=m.merchant_id)).json()
    assert a == b


def test_confidence_bounds_never_out_of_range_via_api(
    db, make_merchant, make_case, make_api_client
):
    m = make_merchant()
    _seed(make_case, m, t_rec=1, t_miss=0, c_rec=0, c_miss=1)
    client = make_api_client()
    body = client.get(INCR.format(m=m.merchant_id)).json()
    for arm in ("treatment", "control"):
        lo, hi = body[arm]["ci_low"], body[arm]["ci_high"]
        assert Decimal("0") <= Decimal(lo) <= Decimal(hi) <= Decimal("1")
    llo, lhi = body["lift"]["ci_low"], body["lift"]["ci_high"]
    assert Decimal("-1") <= Decimal(llo) <= Decimal(lhi) <= Decimal("1")
