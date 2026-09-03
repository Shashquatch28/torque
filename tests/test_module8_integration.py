"""Module 8 §8.6 — the real score drives BOTH the Outreach Coordinator merge
ordering and the human-queue priority, through the single
`outreach_coordinator.priority()` seam (D-098 / D-113). No consumer re-derives
the formula.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal

from torque.coordination import human_queue as HQ
from torque.coordination import merge as M
from torque.coordination.outreach_coordinator import priority
from torque.enums import CaseStatus, LegType
from torque.scoring import compute_recovery_score

_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


# --- one authoritative implementation --------------------------------


def test_priority_seam_returns_the_module8_score(db, make_case):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("6000.00"),
    )
    assert priority(db, case) == compute_recovery_score(db, case).score


def test_consumers_route_through_the_seam_not_the_formula():
    # `human_queue` and `merge` must call the `priority` seam — never
    # `compute_recovery_score` / `benchmarks` / `cost` directly (no duplication).
    hq_src = inspect.getsource(HQ)
    merge_src = inspect.getsource(M)
    for src in (hq_src, merge_src):
        assert "compute_recovery_score" not in src
        assert "torque.scoring.benchmarks" not in src
        assert "torque.scoring.cost" not in src
    assert "priority" in hq_src
    assert "OC.priority" in merge_src
    # the seam itself is the single delegation point
    seam_src = inspect.getsource(priority)
    assert "compute_recovery_score" in seam_src


# --- human queue consumes the score --------------------------------


def test_human_queue_priority_is_the_recovery_score(db, make_case):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.ESCALATED_TO_HUMAN,
        context={"gateway": "razorpay"}, amount_at_risk=Decimal("15000.00"),
    )
    entry = HQ.enqueue(db, case=case, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
    assert entry.priority == compute_recovery_score(db, case).score


def test_human_queue_orders_by_the_recovery_score(db, make_case, make_merchant):
    m = make_merchant()
    # equal amount, but different freshness → different probability → different score
    fresh = make_case(
        merchant=m, leg=LegType.SUBSCRIPTION_FAILURE, status=CaseStatus.ESCALATED_TO_HUMAN,
        amount_at_risk=Decimal("10000.00"),
        context={"mandate_id": "a", "mandate_type": "CARD",
                 "billing_cycle": "1", "subscription_id": "s1"},
    )
    stale = make_case(
        merchant=m, leg=LegType.SUBSCRIPTION_FAILURE, status=CaseStatus.ESCALATED_TO_HUMAN,
        amount_at_risk=Decimal("10000.00"),
        context={"mandate_id": "b", "mandate_type": "CARD",
                 "billing_cycle": "1", "subscription_id": "s2"},
    )
    from datetime import timedelta

    stale.opened_at = _NOW - timedelta(days=30)
    db.flush()
    HQ.enqueue(db, case=stale, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS, now=_NOW)
    HQ.enqueue(db, case=fresh, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS, now=_NOW)

    ordered = HQ.list_for_merchant(db, m.merchant_id)
    assert [e.case_id for e in ordered] == [fresh.case_id, stale.case_id]


# --- merge primary selection consumes the score -------------------


def test_merge_primary_is_the_higher_recovery_score(
    db, seeded_catalog, make_active_run, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty()
    # Same merchant + counterparty, both awaiting a WhatsApp step; different
    # amounts → the higher score owns the merged Action.
    small, run_s, job_s = make_active_run(
        merchant=m, counterparty=cp, leg=LegType.CHECKOUT_ABANDONMENT,
        root_cause_code="NO_PAYMENT_METHOD_ATTEMPTED", amount_at_risk=Decimal("200.00"),
        context={"cart_id": "s", "cart_value": "200.00",
                 "drop_stage": "review", "payment_method_attempted": "NONE"},
    )
    big, run_b, job_b = make_active_run(
        merchant=m, counterparty=cp, leg=LegType.CHECKOUT_ABANDONMENT,
        root_cause_code="NO_PAYMENT_METHOD_ATTEMPTED", amount_at_risk=Decimal("50000.00"),
        context={"cart_id": "b", "cart_value": "50000.00",
                 "drop_stage": "review", "payment_method_attempted": "NONE"},
    )
    now = job_b.fire_at
    job_s.fire_at = now
    db.flush()

    groups = M.merge_groups(db, [job_s, job_b], now=now)
    assert groups, "the two due outreach jobs should merge"
    (items,) = list(groups.values())
    ordered = M._ordered(db, items)
    assert ordered[0].case.case_id == big.case_id
    assert priority(db, big) > priority(db, small)
