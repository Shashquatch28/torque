"""Module 3 — pure classifier tables (Blueprint §3.1 / §3.2). No DB.

Exhaustive coverage of the rule-based lookup: decline-code categories, the
network-directive precedence, the mandate-fact overrides, checkout combinations,
B2B buckets, and the leg-vocabulary invariant (a leg classifier only ever returns
a code from its own §3.1 set).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from torque.diagnosis.classifier import (
    classify_b2b_receivable,
    classify_checkout_abandonment,
    classify_payment_degradation,
    classify_subscription_failure,
)
from torque.diagnosis.decline_codes import (
    KNOWN_CODE_CONFIDENCE,
    OPAQUE_CODE_CONFIDENCE,
    DeclineCategory,
    categorise,
)
from torque.diagnosis.root_causes import VALID_BY_LEG, RootCauseCode, is_hard_decline_for
from torque.enums import (
    ClearingCycleStatus,
    LegType,
    MacTier,
    MandateType,
    PaymentMethodAttempted,
)

RC = RootCauseCode


# --- decline-code categorisation ---------------------------------------------


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("insufficient_funds", DeclineCategory.NSF),
        ("NSF", DeclineCategory.NSF),
        ("Insufficient Funds", DeclineCategory.NSF),  # normalised
        ("card_expired", DeclineCategory.CARD_EXPIRED),
        ("expired-card", DeclineCategory.CARD_EXPIRED),  # dash normalised
        ("stolen_card", DeclineCategory.FRAUD_OR_CANCELLED),
        ("fraud", DeclineCategory.FRAUD_OR_CANCELLED),
        ("recurring_not_supported", DeclineCategory.INSTRUMENT_DEAD),
        ("issuer_declined", DeclineCategory.GENERIC_SOFT),
    ],
)
def test_known_codes_are_high_confidence(code, category):
    cat, conf = categorise(code)
    assert cat is category
    assert conf == KNOWN_CODE_CONFIDENCE


@pytest.mark.parametrize("code", ["BAD_REQUEST_ERROR", "do_not_honour", "wat", "9Q7Z"])
def test_opaque_codes_are_low_confidence(code):
    cat, conf = categorise(code)
    assert cat is DeclineCategory.OPAQUE
    assert conf == OPAQUE_CODE_CONFIDENCE
    assert conf < 0.65  # below T → escalate by construction


# --- payment leg -------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "decline", "code", "confidence", "hard"),
    [
        (MacTier.TIER_1_HARD_STOP, "nsf", RC.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED, 0.95, True),
        (MacTier.TIER_3_INSTRUMENT_DEAD, None, RC.INSTRUMENT_NOT_RECURRING_CAPABLE, 0.95, True),
        (MacTier.TIMED_RETRY, "nsf", RC.ISSUER_SOFT_DECLINE_NSF, 0.75, False),
        (None, "insufficient_funds", RC.ISSUER_SOFT_DECLINE_NSF, 0.75, False),
        (None, "issuer_declined", RC.ISSUER_SOFT_DECLINE_OTHER, 0.75, False),
        (None, "stolen_card", RC.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED, 0.75, True),
        (None, "recurring_not_supported", RC.INSTRUMENT_NOT_RECURRING_CAPABLE, 0.75, True),
        (None, "BAD_REQUEST_ERROR", RC.UNKNOWN_LOW_CONFIDENCE, 0.4, None),
        (None, None, RC.GATEWAY_TIMEOUT, 0.5, False),
    ],
)
def test_payment_classification(tier, decline, code, confidence, hard):
    r = classify_payment_degradation(network_directive_tier=tier, decline_code=decline)
    assert r.root_cause_code is code
    assert r.diagnosis_confidence == confidence
    assert r.is_hard_decline is hard
    assert r.root_cause_code in VALID_BY_LEG[LegType.PAYMENT_DEGRADATION]


def test_payment_tier2_falls_through_to_decline_code():
    """TIER_2 / TIMED do NOT short-circuit — they classify by decline code but
    the tier is retained on the case for Module 5's retry timing (§3.2.1)."""
    r = classify_payment_degradation(
        network_directive_tier=MacTier.TIER_2_CAPPED_RETRY, decline_code="card_expired"
    )
    assert r.root_cause_code is RC.ISSUER_HARD_DECLINE_CARD_EXPIRED
    assert r.diagnosis_confidence == 0.75


def test_payment_nsf_emits_timing_hint():
    r = classify_payment_degradation(network_directive_tier=None, decline_code="nsf")
    assert r.suggested_timing_adjustment == "next_month_end_working_day"


def test_payment_non_nsf_no_timing_hint():
    r = classify_payment_degradation(network_directive_tier=None, decline_code="card_expired")
    assert r.suggested_timing_adjustment is None


# --- subscription leg --------------------------------------------------------


def test_subscription_nach_pending_precedes_everything():
    r = classify_subscription_failure(
        mandate_type=MandateType.NACH,
        network_directive_tier=MacTier.TIER_1_HARD_STOP,  # would otherwise win
        decline_code="stolen_card",
        clearing_cycle_status=ClearingCycleStatus.PENDING_CLEARING,
        mandate_cancelled_at=None,
    )
    assert r.root_cause_code is RC.NACH_CLEARING_PENDING
    assert r.diagnosis_confidence == 1.0


def test_subscription_upi_cancelled_precedes_decline():
    r = classify_subscription_failure(
        mandate_type=MandateType.UPI_AUTOPAY,
        network_directive_tier=None,
        decline_code="insufficient_funds",
        clearing_cycle_status=None,
        mandate_cancelled_at=datetime.now(UTC),
    )
    assert r.root_cause_code is RC.UPI_AUTOPAY_CAP_EXHAUSTED
    assert r.diagnosis_confidence == 1.0


@pytest.mark.parametrize(
    ("tier", "decline", "code", "confidence"),
    [
        (MacTier.TIER_1_HARD_STOP, None, RC.MANDATE_CANCELLED_BY_CUSTOMER, 0.95),
        (MacTier.TIER_3_INSTRUMENT_DEAD, None, RC.INSTRUMENT_NOT_RECURRING_CAPABLE, 0.95),
        (None, "insufficient_funds", RC.NSF_SOFT_DECLINE, 0.75),
        (None, "card_expired", RC.CARD_EXPIRED_OR_REISSUED, 0.75),
        (None, "mandate_cancelled", RC.MANDATE_CANCELLED_BY_CUSTOMER, 0.75),
        (None, "recurring_not_supported", RC.INSTRUMENT_NOT_RECURRING_CAPABLE, 0.75),
        (None, "issuer_declined", RC.NSF_SOFT_DECLINE, 0.75),  # generic soft → retry path
        (None, "BAD_REQUEST_ERROR", RC.UNKNOWN_SUBSCRIPTION_FAILURE, 0.4),
        (None, None, RC.UNKNOWN_SUBSCRIPTION_FAILURE, 0.5),
    ],
)
def test_subscription_classification(tier, decline, code, confidence):
    r = classify_subscription_failure(
        mandate_type=MandateType.CARD,
        network_directive_tier=tier,
        decline_code=decline,
        clearing_cycle_status=None,
        mandate_cancelled_at=None,
    )
    assert r.root_cause_code is code
    assert r.diagnosis_confidence == confidence
    assert r.is_hard_decline is None  # never set for subscription
    assert r.root_cause_code in VALID_BY_LEG[LegType.SUBSCRIPTION_FAILURE]


# --- checkout leg (every verdict below T) ------------------------------------


@pytest.mark.parametrize(
    ("stage", "method", "code", "confidence"),
    [
        ("vpa_entry", PaymentMethodAttempted.UPI_COLLECT, RC.UPI_COLLECT_FRICTION, 0.6),
        ("browsing", PaymentMethodAttempted.NONE, RC.NO_PAYMENT_METHOD_ATTEMPTED, 0.4),
        ("auth_3ds", PaymentMethodAttempted.CARD, RC.AUTH_3DS_TIMEOUT, 0.55),
        ("checkout", PaymentMethodAttempted.CARD, RC.PAYMENT_METHOD_FAILED_MIDFLOW, 0.5),
        ("bank_page", PaymentMethodAttempted.NETBANKING, RC.PAYMENT_METHOD_FAILED_MIDFLOW, 0.5),
        ("intent", PaymentMethodAttempted.UPI_INTENT, RC.PAYMENT_METHOD_FAILED_MIDFLOW, 0.5),
    ],
)
def test_checkout_classification(stage, method, code, confidence):
    r = classify_checkout_abandonment(drop_stage=stage, payment_method_attempted=method)
    assert r.root_cause_code is code
    assert r.diagnosis_confidence == confidence
    assert r.diagnosis_confidence < 0.65  # checkout always escalates
    assert r.root_cause_code in VALID_BY_LEG[LegType.CHECKOUT_ABANDONMENT]


# --- B2B leg -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "pkr", "count", "code", "confidence"),
    [
        (10, 0.9, 5, RC.LIQUIDITY_DELAY_LOW_RISK, 0.8),
        (60, 0.2, 5, RC.LIQUIDITY_DELAY_HIGH_RISK, 0.8),
        (120, 0.5, 5, RC.DISPUTE_SUSPECTED, 0.8),
        (10, None, 1, RC.LIQUIDITY_DELAY_LOW_RISK, 0.4),  # cold start, recent
        (60, None, 1, RC.LIQUIDITY_DELAY_HIGH_RISK, 0.4),  # cold start, old
        (None, None, 0, RC.UNKNOWN_RECEIVABLE_RISK, 0.4),
        (10, 0.9, 2, RC.LIQUIDITY_DELAY_LOW_RISK, 0.4),  # <3 invoices → cold start
    ],
)
def test_b2b_classification(days, pkr, count, code, confidence):
    r = classify_b2b_receivable(
        days_overdue=days, promise_keeping_rate=pkr, prior_invoice_count=count
    )
    assert r.root_cause_code is code
    assert r.diagnosis_confidence == confidence
    assert r.root_cause_code in VALID_BY_LEG[LegType.B2B_RECEIVABLE]


# --- is_hard_decline mapping -------------------------------------------------


def test_is_hard_decline_mapping():
    assert is_hard_decline_for(RC.ISSUER_HARD_DECLINE_CARD_EXPIRED) is True
    assert is_hard_decline_for(RC.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED) is True
    assert is_hard_decline_for(RC.INSTRUMENT_NOT_RECURRING_CAPABLE) is True
    assert is_hard_decline_for(RC.ISSUER_SOFT_DECLINE_NSF) is False
    assert is_hard_decline_for(RC.ISSUER_SOFT_DECLINE_OTHER) is False
    assert is_hard_decline_for(RC.GATEWAY_TIMEOUT) is False
    assert is_hard_decline_for(RC.UNKNOWN_LOW_CONFIDENCE) is None
