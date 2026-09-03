"""Module 6 — the full `SEND_WHATSAPP` guardrail (Blueprint §3 / §5.2 list 2 item 3).

Gate #1 (`Counterparty.whatsapp_opt_in`) AND gate #2 (an approved UTILITY template
for the leg) AND the open-conversation suspension. Systemic hold precedes all of
them. The gate is consulted through the `GuardrailEngine` facade — the same entry
point the runner uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from torque.coordination.guardrail_engine import GuardrailEngine
from torque.coordination.human_queue import HumanQueueReason
from torque.enums import (
    ActionType,
    BlockReason,
    CaseStatus,
    LegType,
    SystemicScope,
)
from torque.execution.guardrails import GuardKind
from torque.models import MerchantCounterparty, SystemicEvent

_NOW = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)  # 13:30 IST — inside 09–21 windows


def _wa_case(
    make_case, make_merchant, make_counterparty, make_wa_template, *, opt_in=True, template=True
):
    m = make_merchant()
    cp = make_counterparty(whatsapp_opt_in=opt_in)
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
    )
    if template:
        make_wa_template(merchant=m, leg_type=LegType.PAYMENT_DEGRADATION)
    return m, cp, case


def _check(db, case):
    return GuardrailEngine.check(
        db, action_type=ActionType.SEND_WHATSAPP, case=case, now=_NOW
    )


def test_no_opt_in_blocks_with_consent_not_obtained(
    db, make_case, make_merchant, make_counterparty, make_wa_template
):
    _, _, case = _wa_case(
        make_case, make_merchant, make_counterparty, make_wa_template, opt_in=False
    )
    d = _check(db, case)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.CONSENT_NOT_OBTAINED


def test_no_approved_template_blocks_with_template_not_approved(
    db, make_case, make_merchant, make_counterparty, make_wa_template
):
    _, _, case = _wa_case(
        make_case, make_merchant, make_counterparty, make_wa_template, opt_in=True, template=False
    )
    d = _check(db, case)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.TEMPLATE_NOT_APPROVED


def test_pending_template_still_blocks(
    db, make_case, make_merchant, make_counterparty, make_wa_template
):
    m = make_merchant()
    cp = make_counterparty(whatsapp_opt_in=True)
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
    )
    make_wa_template(merchant=m, leg_type=LegType.PAYMENT_DEGRADATION, approval_status="PENDING")
    d = _check(db, case)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.TEMPLATE_NOT_APPROVED


def test_both_gates_pass_allows(
    db, make_case, make_merchant, make_counterparty, make_wa_template
):
    _, _, case = _wa_case(make_case, make_merchant, make_counterparty, make_wa_template)
    assert _check(db, case).kind is GuardKind.ALLOW


def test_systemic_hold_precedes_the_channel_gate(
    db, make_case, make_merchant, make_counterparty, make_wa_template
):
    """A case with no opt-in AND under a systemic hold blocks on SYSTEMIC_HOLD —
    the §5.2 order is systemic first, first-failure-wins."""
    m = make_merchant()
    cp = make_counterparty(whatsapp_opt_in=False)  # would fail the channel gate
    ev = SystemicEvent(
        merchant_id=m.merchant_id, scope=SystemicScope.NETWORK_WIDE,
        failure_rate_at_detection=5, detected_at=_NOW, resolved_at=None, affected_case_count=0,
    )
    db.add(ev)
    db.flush()
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
    )
    case.systemic_event_id = ev.systemic_event_id
    db.flush()
    d = _check(db, case)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.SYSTEMIC_HOLD


def test_active_conversation_suspends_the_template_and_flags_human(
    db, make_case, make_merchant, make_counterparty, make_wa_template
):
    """`active_wa_conversation_expires_at > now` → DEFER (not a template send),
    carried on the OUTREACH_COORDINATOR_DEFERRED path, with the case flagged for
    human pickup (Q-F)."""
    m, cp, case = _wa_case(make_case, make_merchant, make_counterparty, make_wa_template)
    expires = _NOW + timedelta(hours=6)
    db.add(
        MerchantCounterparty(
            merchant_id=m.merchant_id, counterparty_id=cp.counterparty_id,
            active_wa_conversation_expires_at=expires,
        )
    )
    db.flush()
    d = _check(db, case)
    assert d.kind is GuardKind.DEFER
    assert d.block_reason is BlockReason.OUTREACH_COORDINATOR_DEFERRED
    assert d.human_queue_reason == str(HumanQueueReason.OPEN_WA_CONVERSATION)
    assert d.defer_until is not None and d.defer_until > _NOW


def test_expired_conversation_window_does_not_suspend(
    db, make_case, make_merchant, make_counterparty, make_wa_template
):
    m, cp, case = _wa_case(make_case, make_merchant, make_counterparty, make_wa_template)
    db.add(
        MerchantCounterparty(
            merchant_id=m.merchant_id, counterparty_id=cp.counterparty_id,
            active_wa_conversation_expires_at=_NOW - timedelta(hours=1),
        )
    )
    db.flush()
    assert _check(db, case).kind is GuardKind.ALLOW
