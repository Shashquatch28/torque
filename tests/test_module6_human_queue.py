"""Module 6 §6.4 — the human queue and its three feeders.

FIFO-per-merchant, keyed on `case_id`, each entry carrying a `reason` and a
`priority` (the Module 8 seam — `amount_at_risk` today). Feeders:
low-confidence `ESCALATED_TO_HUMAN` sweep (Q-H), escalation-ceiling (tested in
`test_module6_escalation_ceiling`), and broken `PromiseToPay`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from torque.coordination import human_queue as HQ
from torque.enums import CaseStatus, LegType, PromiseStatus
from torque.models import HumanQueueEntry
from torque.promises import transition_promise


def _escalated_case(make_case, merchant=None, counterparty=None, amount=Decimal("1000.00")):
    return make_case(
        merchant=merchant, counterparty=counterparty, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.ESCALATED_TO_HUMAN, context={"gateway": "razorpay"},
        amount_at_risk=amount,
    )


def test_enqueue_is_idempotent_on_case_id(db, make_case):
    case = _escalated_case(make_case)
    a = HQ.enqueue(db, case=case, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
    b = HQ.enqueue(db, case=case, reason=HQ.HumanQueueReason.ESCALATION_CEILING)
    assert a.entry_id == b.entry_id
    assert b.reason == str(HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)  # first wins
    rows = db.query(HumanQueueEntry).filter(HumanQueueEntry.case_id == case.case_id).all()
    assert len(rows) == 1


def test_enqueue_defaults_priority_to_module8_recovery_score(db, make_case):
    # D-113: `priority` now defaults to the authoritative Module 8 score
    # (`(probability × amount_at_risk) ÷ cost`), not the `amount_at_risk`
    # placeholder. The queue still orders by "higher score = higher priority".
    from torque.scoring import compute_recovery_score

    case = _escalated_case(make_case, amount=Decimal("4200.00"))
    entry = HQ.enqueue(db, case=case, reason=HQ.HumanQueueReason.PROMISE_BROKEN)
    assert entry.priority == compute_recovery_score(db, case).score
    assert entry.priority > Decimal("4200.00")  # a real economic score, not the raw amount


def test_sweep_enqueues_all_escalated_cases_and_is_idempotent(db, make_case, make_merchant):
    m = make_merchant()
    c1 = _escalated_case(make_case, merchant=m, amount=Decimal("100.00"))
    c2 = _escalated_case(make_case, merchant=m, amount=Decimal("200.00"))
    # a non-escalated case is ignored
    make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.PLAYBOOK_ACTIVE,
              context={"gateway": "razorpay"})

    first = HQ.sweep_escalated_to_human(db, m.merchant_id)
    assert {e.case_id for e in first} == {c1.case_id, c2.case_id}
    second = HQ.sweep_escalated_to_human(db, m.merchant_id)
    assert {e.entry_id for e in second} == {e.entry_id for e in first}  # no duplicates
    assert db.query(HumanQueueEntry).count() == 2


def test_sweep_skips_superseded_cases(db, make_case, make_merchant):
    m = make_merchant()
    canonical = _escalated_case(make_case, merchant=m)
    superseded = _escalated_case(make_case, merchant=m)
    superseded.superseded_by_case_id = canonical.case_id
    db.flush()
    swept = HQ.sweep_escalated_to_human(db, m.merchant_id)
    assert {e.case_id for e in swept} == {canonical.case_id}


def test_list_priority_order_then_fifo_tiebreak(db, make_case, make_merchant):
    m = make_merchant()
    now = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
    low = _escalated_case(make_case, merchant=m, amount=Decimal("100.00"))
    high = _escalated_case(make_case, merchant=m, amount=Decimal("900.00"))
    mid_a = _escalated_case(make_case, merchant=m, amount=Decimal("500.00"))
    mid_b = _escalated_case(make_case, merchant=m, amount=Decimal("500.00"))
    _r = HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS
    HQ.enqueue(db, case=low, reason=_r, now=now)
    HQ.enqueue(db, case=mid_a, reason=_r, now=now + timedelta(minutes=1))
    HQ.enqueue(db, case=mid_b, reason=_r, now=now + timedelta(minutes=2))
    HQ.enqueue(db, case=high, reason=_r, now=now + timedelta(minutes=3))

    by_priority = HQ.list_for_merchant(db, m.merchant_id)
    assert [e.case_id for e in by_priority] == [
        high.case_id, mid_a.case_id, mid_b.case_id, low.case_id
    ]

    fifo = HQ.list_for_merchant(db, m.merchant_id, order="fifo")
    assert [e.case_id for e in fifo] == [low.case_id, mid_a.case_id, mid_b.case_id, high.case_id]


def test_list_is_tenant_scoped(db, make_case, make_merchant):
    a, b = make_merchant(), make_merchant()
    ca = _escalated_case(make_case, merchant=a)
    cb = _escalated_case(make_case, merchant=b)
    HQ.enqueue(db, case=ca, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
    HQ.enqueue(db, case=cb, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
    assert [e.case_id for e in HQ.list_for_merchant(db, a.merchant_id)] == [ca.case_id]
    assert [e.case_id for e in HQ.list_for_merchant(db, b.merchant_id)] == [cb.case_id]


# --- broken-promise feeder (Q — directly-created BROKEN promise) -------------


def test_broken_promise_routes_to_the_queue(db, make_case, make_promise):
    case = make_case(leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.PLAYBOOK_ACTIVE,
                     context={"gateway": "razorpay"}, amount_at_risk=Decimal("777.00"))
    promise = make_promise(case=case)  # created PENDING (the guard requires it)
    transition_promise(promise, PromiseStatus.BROKEN)
    db.flush()

    entry = HQ.route_broken_promise(db, promise)
    assert entry is not None
    assert entry.case_id == case.case_id
    assert entry.reason == str(HQ.HumanQueueReason.PROMISE_BROKEN)
    # D-113: priority is the Module 8 recovery score, not raw amount_at_risk.
    from torque.scoring import compute_recovery_score

    assert entry.priority == compute_recovery_score(db, case).score


def test_pending_promise_does_not_route(db, make_case, make_promise):
    case = make_case(leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.PLAYBOOK_ACTIVE,
                     context={"gateway": "razorpay"})
    promise = make_promise(case=case)
    assert HQ.route_broken_promise(db, promise) is None
    assert db.query(HumanQueueEntry).count() == 0
