"""Module 10 §10.16 / §10.10 — the deterministic demo dataset and the one-click
synthetic scenarios. Real DB.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from torque.demo import DEMO_MERCHANT_ID, DEMO_SCENARIOS, inject_scenario, seed_demo
from torque.enums import ActionOutcome, CaseStatus
from torque.models import Action, HumanQueueEntry, RevenueLeakCase
from torque.reporting import metrics, recovery_summary


def _count(db, **where):
    stmt = select(func.count()).select_from(RevenueLeakCase).where(
        RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID
    )
    for k, v in where.items():
        stmt = stmt.where(getattr(RevenueLeakCase, k) == v)
    return db.scalar(stmt)


def test_seed_builds_a_realistic_mixture(db):
    out = seed_demo(db)
    assert out["seeded"] is True
    assert out["case_count"] >= 15
    # every archetype present
    assert _count(db, status=CaseStatus.RECOVERED) >= 4
    assert _count(db, status=CaseStatus.ESCALATED_TO_HUMAN) >= 1
    assert _count(db, status=CaseStatus.CANCELLED) >= 1
    assert _count(db, status=CaseStatus.PARTIALLY_RECOVERED) >= 1
    assert _count(db, status=CaseStatus.EXHAUSTED) >= 1
    assert _count(db, status=CaseStatus.PLAYBOOK_ACTIVE) >= 3
    # multiple legs
    legs = {
        r for (r,) in db.execute(
            select(RevenueLeakCase.leg_type).where(
                RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID
            ).distinct()
        )
    }
    assert len(legs) == 4
    # blocked + deferred actions exist (exception list)
    blocked = db.scalar(
        select(func.count()).select_from(Action)
        .where(Action.merchant_id == DEMO_MERCHANT_ID)
        .where(Action.outcome == ActionOutcome.BLOCKED_BY_GUARDRAIL)
    )
    assert blocked >= 3
    # queue populated
    assert db.scalar(
        select(func.count()).select_from(HumanQueueEntry)
        .where(HumanQueueEntry.merchant_id == DEMO_MERCHANT_ID)
    ) >= 2
    # every non-terminal case is scored (Module 8)
    unscored = db.scalar(
        select(func.count()).select_from(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID)
        .where(RevenueLeakCase.status == CaseStatus.PLAYBOOK_ACTIVE)
        .where(RevenueLeakCase.recovery_score.is_(None))
    )
    assert unscored == 0


def test_seed_is_deterministic_and_idempotent(db):
    a = seed_demo(db)
    s1 = recovery_summary(db, DEMO_MERCHANT_ID)
    b = seed_demo(db)  # second call, no reset → no-op
    s2 = recovery_summary(db, DEMO_MERCHANT_ID)
    assert b["seeded"] is False
    assert a["case_count"] == b["case_count"]
    assert s1.model_dump() == s2.model_dump()  # identical numbers


def test_seed_reset_rebuilds_the_same_dataset(db):
    seed_demo(db)
    before = recovery_summary(db, DEMO_MERCHANT_ID).model_dump()
    out = seed_demo(db, reset=True)
    after = recovery_summary(db, DEMO_MERCHANT_ID).model_dump()
    assert out["seeded"] is True
    assert before == after  # deterministic clock → identical rebuild


def test_dashboard_numbers_are_backend_derived(db):
    """The report reconciles: by-leg amounts sum to the summary."""
    seed_demo(db)
    s = recovery_summary(db, DEMO_MERCHANT_ID)
    legs = metrics.recovery_by_leg(db, DEMO_MERCHANT_ID)
    from decimal import Decimal

    leg_total = sum((leg.recovered_amount for leg in legs), Decimal("0"))
    assert leg_total == s.recovered_amount
    assert s.recovered_amount > 0
    assert s.revenue_at_risk > s.recovered_amount


_ACT_SCENARIOS = ("payment_failure", "checkout_abandonment")
_RESTRAINT_SCENARIOS = ("hard_stop_mac", "upi_retry_cap", "nach_ceiling")
_CROSS_LEG_SCENARIOS = ("cross_leg_merge", "b2b_invoice_bundle")  # Module 12a / B1


@pytest.mark.parametrize("scenario", [s["key"] for s in DEMO_SCENARIOS])
def test_each_scenario_injects_a_real_case(db, scenario):
    assert set(_ACT_SCENARIOS + _RESTRAINT_SCENARIOS + _CROSS_LEG_SCENARIOS) == {
        s["key"] for s in DEMO_SCENARIOS
    }
    seed_demo(db)
    before = _count(db)
    out = inject_scenario(db, scenario)
    case = db.get(RevenueLeakCase, out["case_id"])
    assert case is not None and case.merchant_id == DEMO_MERCHANT_ID

    if scenario in _ACT_SCENARIOS:
        assert _count(db) == before + 1
        assert out["status"] == "DETECTED"
    elif scenario in _RESTRAINT_SCENARIOS:
        # Decision-K restraint scenarios: the case reached a playbook and a real
        # guardrail block was recorded
        assert _count(db) == before + 1
        assert out["status"] == "PLAYBOOK_ACTIVE"
        assert "block_reason" in out
        blocked = db.scalar(
            select(func.count()).select_from(Action)
            .where(Action.primary_case_id == case.case_id)
            .where(Action.outcome == ActionOutcome.BLOCKED_BY_GUARDRAIL)
        )
        assert blocked == 1
    elif scenario == "cross_leg_merge":
        # One new payment case + one new (immediately-superseded) checkout case.
        assert _count(db) == before + 2
        assert out["merged"] is True
        merged = db.get(RevenueLeakCase, out["merged_case_id"])
        assert merged.superseded_by_case_id == case.case_id
    elif scenario == "b2b_invoice_bundle":
        # The second invoice bundles into the first case — no new case.
        assert _count(db) == before + 1
        assert out["bundled"] is True
        assert out["invoice_count"] == 2


def test_unknown_scenario_raises(db):
    seed_demo(db)
    with pytest.raises(ValueError, match="unknown demo scenario"):
        inject_scenario(db, "not_a_scenario")
