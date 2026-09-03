"""Module 6 — the `GuardrailEngine` facade (Blueprint §6.2 / Part C item 2).

The single interface Module 5 consults. It returns the four-way `GuardDecision`
(ALLOW / BLOCK / DEFER / AUTO_INSERT_PREDEBIT) — the intentional deviation from
the blueprint's narrower `{allow, block_reason?}` wording (D-097 / Q-A) — and
runs the §5.2 sequence first-failure-wins.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from torque.coordination.guardrail_engine import GuardrailEngine
from torque.enums import (
    ActionType,
    BlockReason,
    CaseStatus,
    ClearingCycleStatus,
    LegType,
    MacTier,
    MandateType,
    SystemicScope,
)
from torque.execution.guardrails import GuardKind, check_retry_guardrails
from torque.models import NACHRetryPolicy, SystemicEvent, UPIRetryBudget
from torque.state_machine import apply_network_directive

_NOW = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)  # 13:30 IST
_OFF_PEAK = datetime(2026, 9, 3, 3, 30, tzinfo=UTC)  # 09:00 IST


def _payment_case(make_case, **kw):
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "issuer_declined"},
        root_cause_code="ISSUER_SOFT_DECLINE_OTHER",
        status=CaseStatus.PLAYBOOK_ACTIVE,
        **kw,
    )


def _sub_case(make_case, m, *, mandate_type, mandate_id="mand_ge", **kw):
    return make_case(
        merchant=m, leg=LegType.SUBSCRIPTION_FAILURE,
        context={
            "mandate_id": mandate_id, "mandate_type": mandate_type.value,
            "billing_cycle": "2", "subscription_id": "sub_x",
        },
        root_cause_code="NSF_SOFT_DECLINE", status=CaseStatus.PLAYBOOK_ACTIVE, **kw,
    )


def _check(db, case, action_type, *, now=_NOW):
    return GuardrailEngine.check(db, action_type=action_type, case=case, now=now)


# --- retry parity: the facade delegates to the Module 5 predicate verbatim ---


def test_retry_facade_matches_check_retry_guardrails_network_hard_stop(db, make_case):
    case = _payment_case(make_case)
    apply_network_directive(db, case, mac_code="03", tier=MacTier.TIER_1_HARD_STOP)
    facade = _check(db, case, ActionType.RETRY_PAYMENT)
    direct = check_retry_guardrails(db, case, now=_NOW)
    assert facade == direct
    assert facade.kind is GuardKind.BLOCK
    assert facade.block_reason is BlockReason.NETWORK_HARD_STOP


def test_retry_facade_propagates_defer(db, make_case, make_merchant):
    m = make_merchant()
    case = _sub_case(make_case, m, mandate_type=MandateType.UPI_AUTOPAY, mandate_id="upi_peak")
    db.add(UPIRetryBudget(merchant_id=m.merchant_id, mandate_id="upi_peak", attempts_used=1))
    db.flush()
    peak = datetime(2026, 9, 3, 6, 30, tzinfo=UTC)  # 12:00 IST — inside NPCI peak
    assert _check(db, case, ActionType.RETRY_PAYMENT, now=peak).kind is GuardKind.DEFER


def test_retry_facade_propagates_auto_insert_predebit(db, make_case, make_merchant):
    m = make_merchant()
    case = _sub_case(make_case, m, mandate_type=MandateType.NACH, mandate_id="nach_pd")
    db.add(
        NACHRetryPolicy(
            merchant_id=m.merchant_id, mandate_id="nach_pd",
            clearing_cycle_status=ClearingCycleStatus.RETURNED, dishonour_count_this_fy=0,
        )
    )
    db.flush()
    d = _check(db, case, ActionType.RETRY_PAYMENT)
    assert d.kind is GuardKind.AUTO_INSERT_PREDEBIT
    assert d.predebit_attempt_number == 1


# --- contact sequence: systemic → cross-leg → whatsapp → open-conv → quiet ---


def test_contact_systemic_hold_blocks(db, make_case, make_merchant):
    m = make_merchant()
    ev = SystemicEvent(
        merchant_id=m.merchant_id, scope=SystemicScope.NETWORK_WIDE,
        failure_rate_at_detection=5, detected_at=_NOW, resolved_at=None, affected_case_count=0,
    )
    db.add(ev)
    db.flush()
    case = _payment_case(make_case, merchant=m)
    case.systemic_event_id = ev.systemic_event_id
    db.flush()
    d = _check(db, case, ActionType.SEND_EMAIL)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.SYSTEMIC_HOLD


def test_pre_debit_notification_only_checks_systemic_hold(db, make_case, make_merchant):
    """`SEND_PRE_DEBIT_NOTIFICATION` is a compliance notice — the coordinator and
    WhatsApp gates never apply to it (parity with Module 5)."""
    m = make_merchant()
    case = _sub_case(make_case, m, mandate_type=MandateType.NACH, mandate_id="nach_pdn")
    # No opt-in, no template — would fail the WhatsApp gate if it applied.
    d = _check(db, case, ActionType.SEND_PRE_DEBIT_NOTIFICATION)
    assert d.kind is GuardKind.ALLOW


def test_unknown_action_type_allows(db, make_case):
    case = _payment_case(make_case)
    assert _check(db, case, ActionType.LOG_PROMISE).kind is GuardKind.ALLOW


def test_check_needs_a_resolvable_case(db):
    with pytest.raises(ValueError, match="case"):
        GuardrailEngine.check(db, action_type=ActionType.SEND_EMAIL, now=_NOW)


def test_tenancy_systemic_event_not_read_across_merchants(db, make_case, make_merchant):
    """A merchant-B systemic event never holds a merchant-A case even if the FK is
    (anomalously) set — the scoped lookup returns nothing."""
    a, b = make_merchant(), make_merchant()
    ev_b = SystemicEvent(
        merchant_id=b.merchant_id, scope=SystemicScope.NETWORK_WIDE,
        failure_rate_at_detection=5, detected_at=_NOW, resolved_at=None, affected_case_count=0,
    )
    db.add(ev_b)
    db.flush()
    case_a = _payment_case(make_case, merchant=a)
    case_a.systemic_event_id = ev_b.systemic_event_id
    db.flush()
    assert _check(db, case_a, ActionType.SEND_EMAIL).kind is GuardKind.ALLOW


def test_cross_leg_quiet_period_defers_and_targets_quiet_period_end(
    db, make_case, make_merchant, make_counterparty, make_action
):
    """A different-leg outreach Action within 4h → DEFER on the
    OUTREACH_COORDINATOR_DEFERRED path, fire time at quiet_period_end + offset."""
    m = make_merchant()
    cp = make_counterparty()
    other = make_case(
        merchant=m, counterparty=cp, leg=LegType.SUBSCRIPTION_FAILURE,
        status=CaseStatus.PLAYBOOK_ACTIVE,
        context={
            "mandate_id": "x", "mandate_type": "CARD",
            "billing_cycle": "1", "subscription_id": "s",
        },
    )
    sent_at = _NOW - timedelta(hours=1)
    act = make_action(case=other, action_type=ActionType.SEND_WHATSAPP, channel="whatsapp")
    act.executed_at = sent_at
    db.flush()

    this_case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
    )
    d = _check(db, this_case, ActionType.SEND_EMAIL)
    assert d.kind is GuardKind.DEFER
    assert d.block_reason is BlockReason.OUTREACH_COORDINATOR_DEFERRED
    # quiet period ends 4h after the send (03:00 UTC + 4h = 07:00 UTC ≈ 12:30 IST, in window)
    assert d.defer_until >= sent_at + timedelta(hours=4)


def test_same_leg_prior_action_incurs_no_cross_leg_defer(
    db, make_case, make_merchant, make_counterparty, make_wa_template, make_action
):
    m = make_merchant()
    cp = make_counterparty()
    make_wa_template(merchant=m, leg_type=LegType.PAYMENT_DEGRADATION)
    prior = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
    )
    act = make_action(case=prior, action_type=ActionType.SEND_WHATSAPP, channel="whatsapp")
    act.executed_at = _NOW - timedelta(hours=1)
    db.flush()
    this_case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
    )
    assert _check(db, this_case, ActionType.SEND_WHATSAPP).kind is GuardKind.ALLOW
