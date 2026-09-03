"""`root_cause_code` — Blueprint Module 3 §3.1. **Module 3 owns this enum.**

It is deliberately NOT in `torque.enums` (freezing it in Module 1 would create a
false contract — see `torque.enums` docstring and the `RevenueLeakCase`
`root_cause_code` column note). The DB column stays a plain `String(64)`; this
`StrEnum` is the application-side vocabulary, and `.value` is what is persisted.
"Module 3 owns future refinement" (§3.1) — the values below are the operative
demo set, verbatim from §3.1.
"""

from __future__ import annotations

from enum import StrEnum

from torque.enums import LegType


class RootCauseCode(StrEnum):
    # --- PAYMENT_DEGRADATION (§3.1) -----------------------------------------
    ISSUER_SOFT_DECLINE_NSF = "ISSUER_SOFT_DECLINE_NSF"
    ISSUER_SOFT_DECLINE_OTHER = "ISSUER_SOFT_DECLINE_OTHER"
    ISSUER_HARD_DECLINE_CARD_EXPIRED = "ISSUER_HARD_DECLINE_CARD_EXPIRED"
    ISSUER_HARD_DECLINE_FRAUD_SUSPECTED = "ISSUER_HARD_DECLINE_FRAUD_SUSPECTED"
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    # State label, "not a real diagnosis" (§3.1) — never emitted by the classifier
    # (systemic cases are held by Module 2 §2.5, not diagnosed here). Declared so
    # the vocabulary is complete.
    SYSTEMIC_ISSUER_OUTAGE = "SYSTEMIC_ISSUER_OUTAGE"
    UNKNOWN_LOW_CONFIDENCE = "UNKNOWN_LOW_CONFIDENCE"

    # --- CHECKOUT_ABANDONMENT (§3.1) ----------------------------------------
    UPI_COLLECT_FRICTION = "UPI_COLLECT_FRICTION"
    AUTH_3DS_TIMEOUT = "AUTH_3DS_TIMEOUT"
    NO_PAYMENT_METHOD_ATTEMPTED = "NO_PAYMENT_METHOD_ATTEMPTED"
    PAYMENT_METHOD_FAILED_MIDFLOW = "PAYMENT_METHOD_FAILED_MIDFLOW"
    UNKNOWN_ABANDONMENT = "UNKNOWN_ABANDONMENT"

    # --- SUBSCRIPTION_FAILURE (§3.1) ----------------------------------------
    NSF_SOFT_DECLINE = "NSF_SOFT_DECLINE"
    CARD_EXPIRED_OR_REISSUED = "CARD_EXPIRED_OR_REISSUED"
    MANDATE_CANCELLED_BY_CUSTOMER = "MANDATE_CANCELLED_BY_CUSTOMER"
    UPI_AUTOPAY_CAP_EXHAUSTED = "UPI_AUTOPAY_CAP_EXHAUSTED"
    NACH_CLEARING_PENDING = "NACH_CLEARING_PENDING"
    UNKNOWN_SUBSCRIPTION_FAILURE = "UNKNOWN_SUBSCRIPTION_FAILURE"

    # Shared across PAYMENT_DEGRADATION and SUBSCRIPTION_FAILURE (from Tier 3).
    INSTRUMENT_NOT_RECURRING_CAPABLE = "INSTRUMENT_NOT_RECURRING_CAPABLE"

    # --- B2B_RECEIVABLE (§3.1) ----------------------------------------------
    LIQUIDITY_DELAY_LOW_RISK = "LIQUIDITY_DELAY_LOW_RISK"
    LIQUIDITY_DELAY_HIGH_RISK = "LIQUIDITY_DELAY_HIGH_RISK"
    DISPUTE_SUSPECTED = "DISPUTE_SUSPECTED"
    UNKNOWN_RECEIVABLE_RISK = "UNKNOWN_RECEIVABLE_RISK"


# The root causes each leg is allowed to emit. Used by tests and as an internal
# assertion that a leg classifier never returns a code from another leg's vocab.
VALID_BY_LEG: dict[LegType, frozenset[RootCauseCode]] = {
    LegType.PAYMENT_DEGRADATION: frozenset(
        {
            RootCauseCode.ISSUER_SOFT_DECLINE_NSF,
            RootCauseCode.ISSUER_SOFT_DECLINE_OTHER,
            RootCauseCode.ISSUER_HARD_DECLINE_CARD_EXPIRED,
            RootCauseCode.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED,
            RootCauseCode.INSTRUMENT_NOT_RECURRING_CAPABLE,
            RootCauseCode.GATEWAY_TIMEOUT,
            RootCauseCode.SYSTEMIC_ISSUER_OUTAGE,
            RootCauseCode.UNKNOWN_LOW_CONFIDENCE,
        }
    ),
    LegType.CHECKOUT_ABANDONMENT: frozenset(
        {
            RootCauseCode.UPI_COLLECT_FRICTION,
            RootCauseCode.AUTH_3DS_TIMEOUT,
            RootCauseCode.NO_PAYMENT_METHOD_ATTEMPTED,
            RootCauseCode.PAYMENT_METHOD_FAILED_MIDFLOW,
            RootCauseCode.UNKNOWN_ABANDONMENT,
        }
    ),
    LegType.SUBSCRIPTION_FAILURE: frozenset(
        {
            RootCauseCode.NSF_SOFT_DECLINE,
            RootCauseCode.CARD_EXPIRED_OR_REISSUED,
            RootCauseCode.MANDATE_CANCELLED_BY_CUSTOMER,
            RootCauseCode.INSTRUMENT_NOT_RECURRING_CAPABLE,
            RootCauseCode.UPI_AUTOPAY_CAP_EXHAUSTED,
            RootCauseCode.NACH_CLEARING_PENDING,
            RootCauseCode.UNKNOWN_SUBSCRIPTION_FAILURE,
        }
    ),
    LegType.B2B_RECEIVABLE: frozenset(
        {
            RootCauseCode.LIQUIDITY_DELAY_LOW_RISK,
            RootCauseCode.LIQUIDITY_DELAY_HIGH_RISK,
            RootCauseCode.DISPUTE_SUSPECTED,
            RootCauseCode.UNKNOWN_RECEIVABLE_RISK,
        }
    ),
}

# `is_hard_decline` (PaymentDegradationContext, Module-3-owned per D-058) is
# DERIVED from the PAYMENT_DEGRADATION root cause: hard declines are the ones a
# retry cannot fix (expired card, suspected fraud, structurally non-recurring
# instrument); soft declines are retry/timing candidates. UNKNOWN and the
# SYSTEMIC state-label carry no verdict → `None`.
_PAYMENT_HARD = frozenset(
    {
        RootCauseCode.ISSUER_HARD_DECLINE_CARD_EXPIRED,
        RootCauseCode.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED,
        RootCauseCode.INSTRUMENT_NOT_RECURRING_CAPABLE,
    }
)
_PAYMENT_SOFT = frozenset(
    {
        RootCauseCode.ISSUER_SOFT_DECLINE_NSF,
        RootCauseCode.ISSUER_SOFT_DECLINE_OTHER,
        RootCauseCode.GATEWAY_TIMEOUT,
    }
)


def is_hard_decline_for(code: RootCauseCode) -> bool | None:
    """The `is_hard_decline` verdict a PAYMENT_DEGRADATION `root_cause_code`
    implies. `None` for the unknown / systemic labels (no verdict)."""
    if code in _PAYMENT_HARD:
        return True
    if code in _PAYMENT_SOFT:
        return False
    return None


# Root causes that warrant the §3.4 payday-cycle retry-timing hint. The blueprint
# names `NSF_SOFT_DECLINE` (subscription); the payment-leg NSF code is the exact
# same "insufficient funds → retry after payday" situation, so it is included too
# (documented decision D-079).
_PAYDAY_TIMING_CODES = frozenset(
    {RootCauseCode.NSF_SOFT_DECLINE, RootCauseCode.ISSUER_SOFT_DECLINE_NSF}
)
#: The §3.4 heuristic label. A placeholder assumption ("last working day of
#: month") — no bank-side salary-date visibility exists.
PAYDAY_TIMING_HINT = "next_month_end_working_day"


def timing_hint_for(code: RootCauseCode) -> str | None:
    """The §3.4 `suggested_timing_adjustment` for a root cause, or `None`."""
    return PAYDAY_TIMING_HINT if code in _PAYDAY_TIMING_CODES else None


# Human-readable `root_cause_label` for each code — stored on the case and shown
# in the UI next to the machine code.
LABELS: dict[RootCauseCode, str] = {
    RootCauseCode.ISSUER_SOFT_DECLINE_NSF: "Issuer soft decline — insufficient funds",
    RootCauseCode.ISSUER_SOFT_DECLINE_OTHER: "Issuer soft decline — other/temporary",
    RootCauseCode.ISSUER_HARD_DECLINE_CARD_EXPIRED: "Issuer hard decline — card expired",
    RootCauseCode.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED: (
        "Issuer hard decline — fraud suspected / do-not-honour"
    ),
    RootCauseCode.GATEWAY_TIMEOUT: "Gateway timeout — no issuer response",
    RootCauseCode.SYSTEMIC_ISSUER_OUTAGE: "Systemic issuer/network outage",
    RootCauseCode.UNKNOWN_LOW_CONFIDENCE: "Unknown — opaque decline code, low confidence",
    RootCauseCode.UPI_COLLECT_FRICTION: "UPI Collect friction — dropped at VPA entry",
    RootCauseCode.AUTH_3DS_TIMEOUT: "Card authentication / 3DS timeout",
    RootCauseCode.NO_PAYMENT_METHOD_ATTEMPTED: "No payment method attempted",
    RootCauseCode.PAYMENT_METHOD_FAILED_MIDFLOW: "Payment method failed mid-flow",
    RootCauseCode.UNKNOWN_ABANDONMENT: "Unknown abandonment cause",
    RootCauseCode.NSF_SOFT_DECLINE: "Mandate NSF soft decline — insufficient funds",
    RootCauseCode.CARD_EXPIRED_OR_REISSUED: "Card mandate expired or reissued",
    RootCauseCode.MANDATE_CANCELLED_BY_CUSTOMER: "Mandate cancelled by customer",
    RootCauseCode.UPI_AUTOPAY_CAP_EXHAUSTED: "UPI AutoPay retry cap exhausted",
    RootCauseCode.NACH_CLEARING_PENDING: "NACH clearing pending — not yet failed",
    RootCauseCode.UNKNOWN_SUBSCRIPTION_FAILURE: "Unknown subscription failure",
    RootCauseCode.INSTRUMENT_NOT_RECURRING_CAPABLE: (
        "Instrument cannot support recurring charges"
    ),
    RootCauseCode.LIQUIDITY_DELAY_LOW_RISK: "Receivable liquidity delay — low risk",
    RootCauseCode.LIQUIDITY_DELAY_HIGH_RISK: "Receivable liquidity delay — high risk",
    RootCauseCode.DISPUTE_SUSPECTED: "Dispute suspected — prolonged non-payment",
    RootCauseCode.UNKNOWN_RECEIVABLE_RISK: "Unknown receivable risk — cold-start counterparty",
}


def label_for(code: RootCauseCode) -> str:
    return LABELS[code]
