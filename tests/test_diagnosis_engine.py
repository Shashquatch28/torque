"""Module 3 — Diagnosis Engine end-to-end (Blueprint §3.2 / §3.3).

Drives `diagnose_case` against real cases created through the ORM guard, asserting
the state transitions, the persisted diagnosis fields, the `DIAGNOSIS_COMPLETED`
audit event, and the `T = 0.65` confidence routing across all four legs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from torque.diagnosis import diagnose_case
from torque.diagnosis.engine import DiagnosisOutcome
from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import (
    Actor,
    CaseEventType,
    CaseStatus,
    ClearingCycleStatus,
    LegType,
    MacTier,
    MandateType,
)
from torque.models import (
    B2BInvoice,
    CaseEvent,
    NACHRetryPolicy,
    UPIRetryBudget,
)
from torque.state_machine import apply_network_directive


def _events(db, case, event_type):
    return db.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .where(CaseEvent.event_type == event_type)
    ).all()


def _diagnosis_event(db, case):
    return _events(db, case, CaseEventType.DIAGNOSIS_COMPLETED)[0]


# --- PAYMENT_DEGRADATION -----------------------------------------------------


def test_payment_opaque_code_escalates(db, make_case):
    """Default demo payload (BAD_REQUEST_ERROR, opaque) → 0.4 < T → escalate,
    by construction routing to human review rather than guessing (§3.2.2)."""
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "BAD_REQUEST_ERROR"},
    )
    out = diagnose_case(db, case_id=case.case_id)

    assert out is DiagnosisOutcome.ESCALATED
    db.refresh(case)
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN
    assert case.root_cause_code == RootCauseCode.UNKNOWN_LOW_CONFIDENCE.value
    assert case.diagnosis_confidence == 0.4
    assert case.context["is_hard_decline"] is None  # unknown → no verdict written


def test_payment_known_nsf_routes_to_playbook_with_timing(db, make_case):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "insufficient_funds"},
    )
    out = diagnose_case(db, case_id=case.case_id)

    assert out is DiagnosisOutcome.ROUTED_TO_PLAYBOOK
    db.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE
    assert case.root_cause_code == RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value
    assert case.diagnosis_confidence == 0.75
    assert case.context["is_hard_decline"] is False
    assert case.suggested_timing_adjustment == "next_month_end_working_day"


def test_payment_hard_decline_card_expired_sets_is_hard_decline(db, make_case):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "card_expired"},
    )
    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.ISSUER_HARD_DECLINE_CARD_EXPIRED.value
    assert case.context["is_hard_decline"] is True
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE  # 0.75 ≥ T


def test_payment_network_directive_tier1_precedence(
    db, make_case
):
    """A TIER_1 directive overrides the (soft) decline code — §3.2.1 precedence,
    confidence 0.95, and the DIAGNOSIS_COMPLETED payload echoes the directive."""
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "insufficient_funds"},
    )
    apply_network_directive(db, case, mac_code="03", tier=MacTier.TIER_1_HARD_STOP)

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED.value
    assert case.diagnosis_confidence == 0.95
    assert case.context["is_hard_decline"] is True

    payload = _diagnosis_event(db, case).payload
    assert payload["network_directive"] == {"mac_code": "03", "tier": "TIER_1_HARD_STOP"}


def test_payment_gateway_timeout_when_no_decline_code(db, make_case):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay"},  # no decline_code
    )
    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.GATEWAY_TIMEOUT.value
    assert case.diagnosis_confidence == 0.5
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN  # 0.5 < T


# --- SUBSCRIPTION_FAILURE ----------------------------------------------------


def _sub_ctx(**kw):
    ctx = {
        "mandate_id": "token_diag",
        "mandate_type": MandateType.CARD.value,
        "billing_cycle": "2",
        "subscription_id": "sub_diag",
    }
    ctx.update(kw)
    return ctx


def _set_source_decline_code(db, case, error_code):
    """Subscription decline codes live in the source Event, not the typed
    context — set `payment.entity.error_code` on the case's source Event."""
    from torque.models import Event

    ev = db.get(Event, case.source_event_id)
    ev.raw_payload = {"payload": {"payment": {"entity": {"error_code": error_code}}}}
    db.flush()


def test_subscription_card_nsf_routes_to_playbook(db, make_case):
    case = make_case(leg=LegType.SUBSCRIPTION_FAILURE, context=_sub_ctx())
    _set_source_decline_code(db, case, "insufficient_funds")
    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.NSF_SOFT_DECLINE.value
    assert case.diagnosis_confidence == 0.75
    assert case.suggested_timing_adjustment == "next_month_end_working_day"
    # is_hard_decline is a payment-context field only — never set here.
    assert "is_hard_decline" not in case.context
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE


def test_subscription_nach_pending_is_a_fact(db, make_case, make_merchant):
    m = make_merchant()
    case = make_case(
        merchant=m,
        leg=LegType.SUBSCRIPTION_FAILURE,
        context=_sub_ctx(mandate_type=MandateType.NACH.value, mandate_id="nach_m1"),
    )
    db.add(
        NACHRetryPolicy(
            merchant_id=m.merchant_id,
            mandate_id="nach_m1",
            clearing_cycle_status=ClearingCycleStatus.PENDING_CLEARING,
            dishonour_count_this_fy=0,
        )
    )
    db.flush()

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.NACH_CLEARING_PENDING.value
    assert case.diagnosis_confidence == 1.0
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE


def test_subscription_upi_cancelled_is_a_fact(db, make_case, make_merchant):
    m = make_merchant()
    case = make_case(
        merchant=m,
        leg=LegType.SUBSCRIPTION_FAILURE,
        context=_sub_ctx(mandate_type=MandateType.UPI_AUTOPAY.value, mandate_id="upi_m1"),
    )
    db.add(
        UPIRetryBudget(
            merchant_id=m.merchant_id,
            mandate_id="upi_m1",
            attempts_used=3,
            mandate_cancelled_at=datetime.now(UTC),
        )
    )
    db.flush()

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.UPI_AUTOPAY_CAP_EXHAUSTED.value
    assert case.diagnosis_confidence == 1.0


def test_subscription_nach_returned_falls_through_to_decline(db, make_case, make_merchant):
    """A RETURNED (i.e. actually-failed) NACH presentment is NOT the pending-fact
    path; it classifies by decline code like any other failure."""
    m = make_merchant()
    case = make_case(
        merchant=m,
        leg=LegType.SUBSCRIPTION_FAILURE,
        context=_sub_ctx(mandate_type=MandateType.NACH.value, mandate_id="nach_ret"),
    )
    _set_source_decline_code(db, case, "insufficient_funds")
    db.add(
        NACHRetryPolicy(
            merchant_id=m.merchant_id,
            mandate_id="nach_ret",
            clearing_cycle_status=ClearingCycleStatus.RETURNED,
            dishonour_count_this_fy=1,
        )
    )
    db.flush()

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.NSF_SOFT_DECLINE.value


# --- CHECKOUT_ABANDONMENT ----------------------------------------------------


def _checkout_ctx(**kw):
    ctx = {
        "cart_id": "cart_diag",
        "cart_value": "499.00",
        "drop_stage": "vpa_entry",
        "payment_method_attempted": "UPI_COLLECT",
    }
    ctx.update(kw)
    return ctx


def test_checkout_always_escalates_below_threshold(db, make_case):
    case = make_case(leg=LegType.CHECKOUT_ABANDONMENT, context=_checkout_ctx())
    out = diagnose_case(db, case_id=case.case_id)
    assert out is DiagnosisOutcome.ESCALATED
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.UPI_COLLECT_FRICTION.value
    assert case.diagnosis_confidence == 0.6
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN


def test_checkout_no_method(db, make_case):
    case = make_case(
        leg=LegType.CHECKOUT_ABANDONMENT,
        context=_checkout_ctx(payment_method_attempted="NONE", drop_stage="browsing"),
    )
    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.NO_PAYMENT_METHOD_ATTEMPTED.value
    assert case.diagnosis_confidence == 0.4


# --- B2B_RECEIVABLE ----------------------------------------------------------


def _add_invoice(db, m, cp, case, *, days_overdue, seq):
    inv = B2BInvoice(
        merchant_id=m.merchant_id,
        counterparty_id=cp.counterparty_id,
        case_id=case.case_id if case is not None else None,
        due_date=(datetime.now(UTC) - timedelta(days=days_overdue)).date(),
        days_overdue=days_overdue,
        original_amount=1000,
        outstanding_amount=1000,
    )
    db.add(inv)
    db.flush()
    return inv


def test_b2b_established_low_risk_routes_to_playbook(
    db, make_merchant, make_counterparty, make_case
):
    m, cp = make_merchant(), make_counterparty()
    from torque.models import MerchantCounterparty

    db.add(
        MerchantCounterparty(
            merchant_id=m.merchant_id,
            counterparty_id=cp.counterparty_id,
            promise_keeping_rate=0.9,
        )
    )
    db.flush()
    case = make_case(merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={})
    for i in range(3):
        _add_invoice(db, m, cp, case, days_overdue=10, seq=i)

    out = diagnose_case(db, case_id=case.case_id)
    assert out is DiagnosisOutcome.ROUTED_TO_PLAYBOOK
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.LIQUIDITY_DELAY_LOW_RISK.value
    assert case.diagnosis_confidence == 0.8


def test_b2b_cold_start_escalates(db, make_merchant, make_counterparty, make_case):
    m, cp = make_merchant(), make_counterparty()
    case = make_case(merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={})
    _add_invoice(db, m, cp, case, days_overdue=20, seq=0)

    out = diagnose_case(db, case_id=case.case_id)
    assert out is DiagnosisOutcome.ESCALATED
    db.refresh(case)
    assert case.diagnosis_confidence == 0.4
    assert case.root_cause_code == RootCauseCode.LIQUIDITY_DELAY_LOW_RISK.value


def test_b2b_established_dispute_suspected(
    db, make_merchant, make_counterparty, make_case
):
    m, cp = make_merchant(), make_counterparty()
    from torque.models import MerchantCounterparty

    db.add(
        MerchantCounterparty(
            merchant_id=m.merchant_id,
            counterparty_id=cp.counterparty_id,
            promise_keeping_rate=0.5,
        )
    )
    db.flush()
    case = make_case(merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={})
    for i in range(3):
        _add_invoice(db, m, cp, case, days_overdue=120, seq=i)

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code == RootCauseCode.DISPUTE_SUSPECTED.value


# --- audit + transition sequence --------------------------------------------


def test_full_event_sequence_detected_to_playbook(db, make_case):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "insufficient_funds"},
    )
    diagnose_case(db, case_id=case.case_id)

    status_events = _events(db, case, CaseEventType.STATUS_CHANGED)
    transitions = [(e.payload["from_status"], e.payload["to_status"]) for e in status_events]
    assert ("DETECTED", "DIAGNOSING") in transitions
    assert ("DIAGNOSING", "PLAYBOOK_ACTIVE") in transitions

    diag = _diagnosis_event(db, case)
    assert diag.actor is Actor.AGENT
    assert diag.reasoning  # non-empty explainability payload
    assert diag.payload["root_cause_code"] == RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value


def test_diagnosis_completed_payload_none_directive(db, make_case):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "insufficient_funds"},
    )
    diagnose_case(db, case_id=case.case_id)
    assert _diagnosis_event(db, case).payload["network_directive"] is None
