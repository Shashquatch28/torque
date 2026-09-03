"""Module 5 — execution-time guardrails & retry-budget consumption (Blueprint §5.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from torque.enums import (
    BlockReason,
    CaseStatus,
    ClearingCycleStatus,
    LegType,
    MacTier,
    MandateType,
)
from torque.execution import execute_due_jobs
from torque.execution.guardrails import (
    GuardKind,
    check_contact_guardrails,
    check_retry_guardrails,
)
from torque.models import (
    CardRetryBudget,
    Event,
    NACHRetryPolicy,
    PreDebitNotification,
    SystemicEvent,
    UPIRetryBudget,
)
from torque.state_machine import apply_network_directive

_NOW = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)  # 13:30 IST — in most windows, in UPI peak


def _payment_case(make_case, **kw):
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "issuer_declined"},
        root_cause_code="ISSUER_SOFT_DECLINE_OTHER",
        status=CaseStatus.PLAYBOOK_ACTIVE,
        **kw,
    )


def _sub_case(make_case, m, *, mandate_type, mandate_id="mand_x", **kw):
    return make_case(
        merchant=m,
        leg=LegType.SUBSCRIPTION_FAILURE,
        context={
            "mandate_id": mandate_id,
            "mandate_type": mandate_type.value,
            "billing_cycle": "2",
            "subscription_id": "sub_x",
        },
        root_cause_code="NSF_SOFT_DECLINE",
        status=CaseStatus.PLAYBOOK_ACTIVE,
        **kw,
    )


def _set_card_token(db, case, token):
    ev = db.get(Event, case.source_event_id)
    ev.raw_payload = {"payload": {"payment": {"entity": {"token_id": token}}}}
    db.flush()


# --- network hard-stop -------------------------------------------------------


def test_network_hard_stop_blocks_retry(db, make_case):
    case = _payment_case(make_case)
    apply_network_directive(db, case, mac_code="03", tier=MacTier.TIER_1_HARD_STOP)
    d = check_retry_guardrails(db, case, now=_NOW)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.NETWORK_HARD_STOP


# --- card budget -------------------------------------------------------------


def test_card_budget_exhausted_blocks(db, make_case, make_merchant):
    m = make_merchant()
    case = _payment_case(make_case, merchant=m)
    _set_card_token(db, case, "tok_capped")
    db.add(
        CardRetryBudget(
            merchant_id=m.merchant_id, card_token_hash="tok_capped",
            attempts_used_24h=10, attempts_used_30d=12, hard_stop=False,
        )
    )
    db.flush()
    d = check_retry_guardrails(db, case, now=_NOW)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.CARD_NETWORK_LIMIT


def test_card_budget_consumed_on_execute(db, make_active_run, make_merchant):
    m = make_merchant(risk_appetite_config={"payday_cycle_override_enabled": False})
    case, run, job = make_active_run(
        merchant=m, root_cause_code="ISSUER_SOFT_DECLINE_OTHER",
        context={"gateway": "razorpay", "decline_code": "issuer_declined"},
    )
    _set_card_token(db, case, "tok_live")
    db.add(
        CardRetryBudget(
            merchant_id=m.merchant_id, card_token_hash="tok_live",
            attempts_used_24h=1, attempts_used_30d=1, hard_stop=False,
        )
    )
    db.flush()
    # execute the first step (retry_1) → the card budget increments once.
    execute_due_jobs(db, leg_types=(LegType.PAYMENT_DEGRADATION,), now=job.fire_at)
    budget = db.scalars(
        select(CardRetryBudget).where(CardRetryBudget.card_token_hash == "tok_live")
    ).one()
    assert budget.attempts_used_24h == 2
    assert budget.attempts_used_30d == 2


# --- UPI hard cap ------------------------------------------------------------


def test_upi_cap_blocks_fourth_attempt(db, make_case, make_merchant):
    m = make_merchant()
    case = _sub_case(make_case, m, mandate_type=MandateType.UPI_AUTOPAY, mandate_id="upi_capped")
    db.add(UPIRetryBudget(merchant_id=m.merchant_id, mandate_id="upi_capped", attempts_used=3))
    db.flush()
    # outside the NPCI peak so the cap (not the window) is what blocks.
    off_peak = datetime(2026, 9, 3, 3, 30, tzinfo=UTC)  # 09:00 IST
    d = check_retry_guardrails(db, case, now=off_peak)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.UPI_RETRY_CAP_EXCEEDED


def test_upi_mandate_cancelled_blocks(db, make_case, make_merchant):
    m = make_merchant()
    case = _sub_case(make_case, m, mandate_type=MandateType.UPI_AUTOPAY, mandate_id="upi_cxl")
    db.add(
        UPIRetryBudget(
            merchant_id=m.merchant_id, mandate_id="upi_cxl", attempts_used=1,
            mandate_cancelled_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    db.flush()
    off_peak = datetime(2026, 9, 3, 3, 30, tzinfo=UTC)
    d = check_retry_guardrails(db, case, now=off_peak)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.UPI_RETRY_CAP_EXCEEDED


def test_upi_peak_window_defers(db, make_case, make_merchant):
    m = make_merchant()
    case = _sub_case(make_case, m, mandate_type=MandateType.UPI_AUTOPAY, mandate_id="upi_ok")
    db.add(UPIRetryBudget(merchant_id=m.merchant_id, mandate_id="upi_ok", attempts_used=1))
    db.flush()
    peak = datetime(2026, 9, 3, 6, 30, tzinfo=UTC)  # 12:00 IST — inside the 10–13 peak
    d = check_retry_guardrails(db, case, now=peak)
    assert d.kind is GuardKind.DEFER


# --- NACH --------------------------------------------------------------------


def test_nach_ceiling_blocks(db, make_case, make_merchant):
    m = make_merchant()
    case = _sub_case(make_case, m, mandate_type=MandateType.NACH, mandate_id="nach_full")
    db.add(
        NACHRetryPolicy(
            merchant_id=m.merchant_id, mandate_id="nach_full",
            clearing_cycle_status=ClearingCycleStatus.RETURNED, dishonour_count_this_fy=3,
        )
    )
    db.flush()
    d = check_retry_guardrails(db, case, now=_NOW)
    assert d.kind is GuardKind.BLOCK
    assert d.block_reason is BlockReason.NACH_CEILING_REACHED


# --- systemic hold -----------------------------------------------------------


def test_systemic_hold_blocks_retry_and_contact(db, make_case, make_merchant):
    from torque.enums import SystemicScope

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

    assert check_retry_guardrails(db, case, now=_NOW).block_reason is BlockReason.SYSTEMIC_HOLD
    assert check_contact_guardrails(db, case, now=_NOW).block_reason is BlockReason.SYSTEMIC_HOLD


def test_resolved_systemic_event_does_not_block(db, make_case, make_merchant):
    from torque.enums import SystemicScope

    m = make_merchant()
    ev = SystemicEvent(
        merchant_id=m.merchant_id, scope=SystemicScope.NETWORK_WIDE,
        failure_rate_at_detection=5, detected_at=_NOW - timedelta(hours=2),
        resolved_at=_NOW, affected_case_count=0,
    )
    db.add(ev)
    db.flush()
    case = _payment_case(make_case, merchant=m)
    case.systemic_event_id = ev.systemic_event_id
    db.flush()
    assert check_contact_guardrails(db, case, now=_NOW).kind is GuardKind.ALLOW


# --- pre-debit auto-insert (§5.2.3) ------------------------------------------


def test_subscription_retry_without_predebit_auto_inserts(db, make_case, make_merchant):
    m = make_merchant()
    case = _sub_case(make_case, m, mandate_type=MandateType.NACH, mandate_id="nach_pd")
    # NACH eligible, but no pre-debit notice on record → self-heal.
    db.add(
        NACHRetryPolicy(
            merchant_id=m.merchant_id, mandate_id="nach_pd",
            clearing_cycle_status=ClearingCycleStatus.RETURNED, dishonour_count_this_fy=0,
        )
    )
    db.flush()
    d = check_retry_guardrails(db, case, now=_NOW)
    assert d.kind is GuardKind.AUTO_INSERT_PREDEBIT
    assert d.predebit_attempt_number == 1


def test_predebit_satisfied_allows_retry(db, make_case, make_merchant):
    m = make_merchant()
    case = _sub_case(make_case, m, mandate_type=MandateType.NACH, mandate_id="nach_ok")
    db.add(
        NACHRetryPolicy(
            merchant_id=m.merchant_id, mandate_id="nach_ok",
            clearing_cycle_status=ClearingCycleStatus.RETURNED, dishonour_count_this_fy=0,
        )
    )
    db.add(
        PreDebitNotification(
            merchant_id=m.merchant_id, case_id=case.case_id,
            notified_at=_NOW - timedelta(hours=25), covers_attempt_number=1,
            channel="whatsapp", notified_amount=case.amount_at_risk,
        )
    )
    db.flush()
    assert check_retry_guardrails(db, case, now=_NOW).kind is GuardKind.ALLOW


def test_upi_playbook_execution_writes_predebit_before_retry(
    db, make_active_run, drain_run, make_merchant
):
    m = make_merchant(risk_appetite_config={"payday_cycle_override_enabled": False})
    case, run, job = make_active_run(
        merchant=m,
        leg=LegType.SUBSCRIPTION_FAILURE,
        root_cause_code="NSF_SOFT_DECLINE",
        context={
            "mandate_id": "upi_run", "mandate_type": "UPI_AUTOPAY",
            "billing_cycle": "2", "subscription_id": "sub_run",
        },
    )
    db.add(UPIRetryBudget(merchant_id=m.merchant_id, mandate_id="upi_run", attempts_used=1))
    db.flush()
    # Graph: predebit → retry → escalate. Draining fires the pre-debit node first,
    # which records a PreDebitNotification covering the retry, so no auto-insert.
    drain_run(run)
    notices = db.scalars(
        select(PreDebitNotification).where(PreDebitNotification.case_id == case.case_id)
    ).all()
    assert len(notices) >= 1
    assert notices[0].covers_attempt_number == 1
