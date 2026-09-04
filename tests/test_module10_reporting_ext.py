"""Module 10 §10.4 / §10.5 / §10.7 / §10.17 — the reporting additions:
top-at-risk (backend score order), human-queue list (priority order),
recent-activity feed (newest first), and the case-detail score breakdown.
"""

from __future__ import annotations

from decimal import Decimal

from tests.module9_helpers import add_action
from torque.coordination import human_queue as HQ
from torque.enums import ActionOutcome, BlockReason, CaseStatus, LegType
from torque.reporting import (
    case_detail,
    human_queue_list,
    recent_activity,
    top_at_risk_cases,
)
from torque.scoring.score import score_case


def _open(make_case, m, *, amount, **kw):
    return make_case(
        merchant=m, leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
        amount_at_risk=Decimal(str(amount)), status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF", diagnosis_confidence=0.85, **kw,
    )


def test_top_at_risk_is_ordered_by_backend_score_desc(db, make_merchant, make_case):
    m = make_merchant()
    small = _open(make_case, m, amount="1000.00")
    big = _open(make_case, m, amount="90000.00")
    mid = _open(make_case, m, amount="9000.00")
    for c in (small, big, mid):
        score_case(db, c)

    out = top_at_risk_cases(db, m.merchant_id, limit=10)
    ids = [i.case_id for i in out.items]
    assert ids == [str(big.case_id), str(mid.case_id), str(small.case_id)]
    scores = [i.recovery_score for i in out.items]
    assert scores == sorted(scores, reverse=True)
    assert all(i.recovery_probability is not None for i in out.items)


def test_top_at_risk_excludes_terminal_cases(db, make_merchant, make_case):
    from tests.module9_helpers import set_recovery
    from torque.enums import RecoveryType

    m = make_merchant()
    live = _open(make_case, m, amount="5000.00")
    score_case(db, live)
    done = _open(make_case, m, amount="5000.00")
    set_recovery(db, done, recovery_type=RecoveryType.AGENT_ASSISTED, amount="5000.00")
    exhausted = _open(make_case, m, amount="5000.00")
    exhausted.status = CaseStatus.EXHAUSTED
    db.flush()

    ids = {i.case_id for i in top_at_risk_cases(db, m.merchant_id).items}
    assert ids == {str(live.case_id)}


def test_human_queue_list_is_priority_ordered(db, make_merchant, make_case):
    m = make_merchant()
    low = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                    context={"gateway": "razorpay"}, amount_at_risk=Decimal("100.00"),
                    status=CaseStatus.ESCALATED_TO_HUMAN)
    high = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                     context={"gateway": "razorpay"}, amount_at_risk=Decimal("50000.00"),
                     status=CaseStatus.ESCALATED_TO_HUMAN)
    HQ.enqueue(db, case=low, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
    HQ.enqueue(db, case=high, reason=HQ.HumanQueueReason.ESCALATION_CEILING)

    out = human_queue_list(db, m.merchant_id)
    assert [i.case_id for i in out.items] == [str(high.case_id), str(low.case_id)]
    assert out.items[0].priority >= out.items[1].priority
    assert out.items[0].reason == "ESCALATION_CEILING"
    assert out.items[0].counterparty_label


def test_recent_activity_is_newest_first_and_tenant_scoped(db, make_merchant, make_case):
    a, b = make_merchant(), make_merchant()
    ca = _open(make_case, a, amount="1000.00")
    add_action(db, ca)  # writes ACTION_EXECUTED
    add_action(db, ca, outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
               block_reason=BlockReason.NETWORK_HARD_STOP)
    cb = _open(make_case, b, amount="1000.00")
    add_action(db, cb)

    feed = recent_activity(db, a.merchant_id, limit=20)
    seqs = [e.event_seq_id for e in feed.items]
    assert seqs == sorted(seqs, reverse=True)
    assert all(e.case_id == str(ca.case_id) for e in feed.items)  # never b's
    assert "ACTION_BLOCKED" in {e.event_type for e in feed.items}


def test_case_detail_carries_the_module8_breakdown(db, make_merchant, make_case):
    m = make_merchant()
    c = _open(make_case, m, amount="12400.00")
    score_case(db, c)
    d = case_detail(db, m.merchant_id, c.case_id)
    assert d.recovery_score_breakdown is not None
    assert "explain" in d.recovery_score_breakdown
    assert d.recovery_probability is not None
    assert d.counterparty_label
    assert d.root_cause_code == "ISSUER_SOFT_DECLINE_NSF"
    # the "why" lines come straight from Module 8
    why = d.recovery_score_breakdown["explain"]["why"]
    assert isinstance(why, list) and why


def test_case_detail_cross_tenant_returns_none(db, make_merchant, make_case):
    a, b = make_merchant(), make_merchant()
    c = _open(make_case, a, amount="1000.00")
    assert case_detail(db, b.merchant_id, c.case_id) is None
