"""Module 9 §9.7 — operational / exception reporting: blocked, deferred,
failed, escalated, stopping-rule / terminal outcomes. Reporting consumes the
authoritative outcomes; it defines no guardrail logic.
"""

from __future__ import annotations

from decimal import Decimal

from tests.module9_helpers import add_action, set_recovery, set_status
from torque.coordination import human_queue as HQ
from torque.enums import ActionOutcome, ActionType, BlockReason, CaseStatus, LegType, RecoveryType
from torque.reporting import metrics

_A = RecoveryType.AGENT_ASSISTED


def _pd(make_case, m, *, amount, **kw):
    return make_case(
        merchant=m, leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay"}, amount_at_risk=Decimal(str(amount)), **kw,
    )


def test_blocked_actions_grouped_by_reason(db, make_merchant, make_case):
    m = make_merchant()
    c1 = _pd(make_case, m, amount="1000.00")
    c2 = _pd(make_case, m, amount="2000.00")
    add_action(db, c1, outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
               block_reason=BlockReason.NETWORK_HARD_STOP)
    add_action(db, c1, outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
               block_reason=BlockReason.NETWORK_HARD_STOP)
    add_action(db, c2, outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
               block_reason=BlockReason.CONSENT_NOT_OBTAINED)

    rep = metrics.operational_exceptions(db, m.merchant_id)
    by_reason = {b.block_reason: b for b in rep.blocked_by_reason}
    assert by_reason["NETWORK_HARD_STOP"].action_count == 2
    assert by_reason["NETWORK_HARD_STOP"].case_count == 1
    assert by_reason["NETWORK_HARD_STOP"].revenue_at_risk == Decimal("1000.00")
    assert by_reason["CONSENT_NOT_OBTAINED"].case_count == 1

    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.blocked_amount == Decimal("3000.00")  # both cases, deduped, once each


def test_deferred_actions_counted_from_outreach_coordinator_defer(db, make_merchant, make_case):
    m = make_merchant()
    c = _pd(make_case, m, amount="5000.00")
    add_action(db, c, outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
               block_reason=BlockReason.OUTREACH_COORDINATOR_DEFERRED)
    rep = metrics.operational_exceptions(db, m.merchant_id)
    assert rep.deferred_action_count == 1
    assert rep.deferred_case_count == 1
    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.deferred_amount == Decimal("5000.00")
    # a deferred action is also a BLOCKED_BY_GUARDRAIL row → in blocked_by_reason
    assert any(
        b.block_reason == "OUTREACH_COORDINATOR_DEFERRED" for b in rep.blocked_by_reason
    )


def test_failed_and_no_response_actions_by_type(db, make_merchant, make_case):
    m = make_merchant()
    c = _pd(make_case, m, amount="1000.00")
    add_action(db, c, action_type=ActionType.RETRY_PAYMENT, channel=None,
               outcome=ActionOutcome.FAILED)
    add_action(db, c, action_type=ActionType.SEND_WHATSAPP,
               outcome=ActionOutcome.NO_RESPONSE)
    add_action(db, c, action_type=ActionType.SEND_WHATSAPP,
               outcome=ActionOutcome.NO_RESPONSE)

    rep = metrics.operational_exceptions(db, m.merchant_id)
    found = {(f.action_type, f.outcome): f.action_count for f in rep.failed_by_type}
    assert found[("RETRY_PAYMENT", "FAILED")] == 1
    assert found[("SEND_WHATSAPP", "NO_RESPONSE")] == 2


def test_escalations_from_status_and_human_queue(db, make_merchant, make_case):
    m = make_merchant()
    esc = _pd(make_case, m, amount="1000.00", status=CaseStatus.ESCALATED_TO_HUMAN)
    HQ.enqueue(db, case=esc, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
    promise_case = _pd(make_case, m, amount="2000.00", status=CaseStatus.PLAYBOOK_ACTIVE)
    HQ.enqueue(db, case=promise_case, reason=HQ.HumanQueueReason.PROMISE_BROKEN)

    rep = metrics.operational_exceptions(db, m.merchant_id)
    assert rep.escalated_case_count == 2  # ESCALATED_TO_HUMAN ∪ queue
    by_reason = {e.reason: e.case_count for e in rep.escalations_by_reason}
    assert by_reason["LOW_CONFIDENCE_DIAGNOSIS"] == 1
    assert by_reason["PROMISE_BROKEN"] == 1
    assert metrics.recovery_summary(db, m.merchant_id).escalated_case_count == 2


def test_terminal_status_breakdown(db, make_merchant, make_case):
    m = make_merchant()
    rec = _pd(make_case, m, amount="1000.00")
    exhausted = _pd(make_case, m, amount="2000.00")
    written_off = _pd(make_case, m, amount="3000.00")
    _open = _pd(make_case, m, amount="4000.00")
    set_recovery(db, rec, recovery_type=_A, amount="1000.00")
    set_status(db, exhausted, CaseStatus.EXHAUSTED)
    set_status(db, written_off, CaseStatus.WRITTEN_OFF)

    rep = metrics.operational_exceptions(db, m.merchant_id)
    term = {t.status: t for t in rep.terminal_by_status}
    assert term["RECOVERED"].case_count == 1
    assert term["RECOVERED"].recovered_amount == Decimal("1000.00")
    assert term["EXHAUSTED"].case_count == 1
    assert term["EXHAUSTED"].revenue_at_risk == Decimal("2000.00")
    assert term["WRITTEN_OFF"].case_count == 1
    assert "DETECTED" not in term  # open, not terminal
    assert _open.status is CaseStatus.DETECTED

    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.written_off_case_count == 1
    assert s.exhausted_case_count == 1


def test_no_exceptions_is_empty_not_error(db, make_merchant):
    m = make_merchant()
    rep = metrics.operational_exceptions(db, m.merchant_id)
    assert rep.blocked_by_reason == []
    assert rep.failed_by_type == []
    assert rep.escalations_by_reason == []
    assert rep.terminal_by_status == []
    assert rep.deferred_action_count == 0
