"""Pure, side-effect-free per-leg classification (Blueprint §3.2).

Every function takes already-gathered plain inputs (no `Session`, no DB) and
returns a `DiagnosisResult`. The engine (`torque.diagnosis.engine`) does the
tenant-scoped I/O to assemble the inputs and to persist the result; keeping the
rules pure makes them exhaustively table-testable.

"Rule-based lookup tables for the demo, no ML model" (§3.5) — the same
philosophy as Module 8's Decision F.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from torque.diagnosis.decline_codes import DeclineCategory, categorise
from torque.diagnosis.root_causes import (
    RootCauseCode,
    is_hard_decline_for,
    label_for,
    timing_hint_for,
)
from torque.enums import (
    ClearingCycleStatus,
    MacTier,
    MandateType,
    PaymentMethodAttempted,
)

# --- confidence constants (Blueprint §3.2, verbatim) -------------------------
NETWORK_DIRECTIVE_CONFIDENCE = 0.95  # §3.2.1 TIER_1 / TIER_3 precedence
GATEWAY_TIMEOUT_CONFIDENCE = 0.5  # §3.2.3 missing decline_code
MANDATE_FACT_CONFIDENCE = 1.0  # §3.2.4 facts, not inferences
CHECKOUT_UPI_COLLECT_CONFIDENCE = 0.6  # §3.2 checkout
CHECKOUT_AUTH_3DS_CONFIDENCE = 0.55
CHECKOUT_MIDFLOW_CONFIDENCE = 0.5
CHECKOUT_NO_METHOD_CONFIDENCE = 0.4  # §3.2 checkout ("genuinely ambiguous")
CHECKOUT_UNKNOWN_CONFIDENCE = 0.35
B2B_ESTABLISHED_CONFIDENCE = 0.8  # §3.2 B2B (3+ prior invoices)
B2B_COLDSTART_CONFIDENCE = 0.4  # §3.2 B2B (cold-start)

# --- B2B bucketing thresholds (demo-scope, Module 3 owns refinement) ---------
B2B_DISPUTE_DAYS_OVERDUE = 90  # beyond this, "dispute" is the coarse fallback
B2B_HIGH_RISK_SCORE = 30.0  # days_overdue × (1 − promise_keeping_rate)
B2B_COLDSTART_HIGH_RISK_DAYS = 45  # cold-start bucketing on days_overdue alone


@dataclass(frozen=True)
class DiagnosisResult:
    """The classifier's verdict for one case."""

    root_cause_code: RootCauseCode
    diagnosis_confidence: float
    reasoning: str
    #: PAYMENT_DEGRADATION only (the leg whose context carries the field);
    #: `None` for every other leg and for the unknown/systemic payment labels.
    is_hard_decline: bool | None = None
    #: §3.4 payday-cycle retry-timing hint, or `None`.
    suggested_timing_adjustment: str | None = None

    @property
    def root_cause_label(self) -> str:
        return label_for(self.root_cause_code)


# --- PAYMENT_DEGRADATION + SUBSCRIPTION_FAILURE shared decline path -----------

# Category → PAYMENT_DEGRADATION root cause.
_PAYMENT_BY_CATEGORY: dict[DeclineCategory, RootCauseCode] = {
    DeclineCategory.NSF: RootCauseCode.ISSUER_SOFT_DECLINE_NSF,
    DeclineCategory.CARD_EXPIRED: RootCauseCode.ISSUER_HARD_DECLINE_CARD_EXPIRED,
    DeclineCategory.FRAUD_OR_CANCELLED: RootCauseCode.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED,
    DeclineCategory.INSTRUMENT_DEAD: RootCauseCode.INSTRUMENT_NOT_RECURRING_CAPABLE,
    DeclineCategory.GENERIC_SOFT: RootCauseCode.ISSUER_SOFT_DECLINE_OTHER,
    DeclineCategory.OPAQUE: RootCauseCode.UNKNOWN_LOW_CONFIDENCE,
}

# Category → SUBSCRIPTION_FAILURE root cause. Subscription has no
# "soft-decline-other" or "gateway-timeout" code; a documented non-NSF soft
# decline maps onto the retryable NSF soft path (its recovery playbook), and an
# opaque code onto the leg's unknown label.
_SUBSCRIPTION_BY_CATEGORY: dict[DeclineCategory, RootCauseCode] = {
    DeclineCategory.NSF: RootCauseCode.NSF_SOFT_DECLINE,
    DeclineCategory.CARD_EXPIRED: RootCauseCode.CARD_EXPIRED_OR_REISSUED,
    DeclineCategory.FRAUD_OR_CANCELLED: RootCauseCode.MANDATE_CANCELLED_BY_CUSTOMER,
    DeclineCategory.INSTRUMENT_DEAD: RootCauseCode.INSTRUMENT_NOT_RECURRING_CAPABLE,
    DeclineCategory.GENERIC_SOFT: RootCauseCode.NSF_SOFT_DECLINE,
    DeclineCategory.OPAQUE: RootCauseCode.UNKNOWN_SUBSCRIPTION_FAILURE,
}


def _finish_payment(code: RootCauseCode, confidence: float, reasoning: str) -> DiagnosisResult:
    return DiagnosisResult(
        root_cause_code=code,
        diagnosis_confidence=confidence,
        reasoning=reasoning,
        is_hard_decline=is_hard_decline_for(code),
        suggested_timing_adjustment=timing_hint_for(code),
    )


def _finish_subscription(
    code: RootCauseCode, confidence: float, reasoning: str
) -> DiagnosisResult:
    # is_hard_decline is a PAYMENT_DEGRADATION context field only — never set for
    # subscription (its context has no such field).
    return DiagnosisResult(
        root_cause_code=code,
        diagnosis_confidence=confidence,
        reasoning=reasoning,
        is_hard_decline=None,
        suggested_timing_adjustment=timing_hint_for(code),
    )


def classify_payment_degradation(
    *, network_directive_tier: MacTier | None, decline_code: str | None
) -> DiagnosisResult:
    """§3.2 steps 1–3 for PAYMENT_DEGRADATION."""
    # Step 1 — network directive precedence (mechanical, set at ingestion or,
    # per §5.3, at first touch; already the most-restrictive-ever tier).
    if network_directive_tier is MacTier.TIER_1_HARD_STOP:
        return _finish_payment(
            RootCauseCode.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED,
            NETWORK_DIRECTIVE_CONFIDENCE,
            "TIER_1_HARD_STOP network directive takes precedence over decline-code "
            "classification (§3.2.1) — treated as a suspected-fraud hard stop.",
        )
    if network_directive_tier is MacTier.TIER_3_INSTRUMENT_DEAD:
        return _finish_payment(
            RootCauseCode.INSTRUMENT_NOT_RECURRING_CAPABLE,
            NETWORK_DIRECTIVE_CONFIDENCE,
            "TIER_3_INSTRUMENT_DEAD network directive takes precedence (§3.2.1) — "
            "the instrument structurally cannot support recurring charges.",
        )
    # TIER_2 / TIMED_RETRY / None fall through, retaining the tier for Module 5.

    # Step 3 — missing decline_code entirely (gateway timeout, no response).
    if not decline_code:
        return _finish_payment(
            RootCauseCode.GATEWAY_TIMEOUT,
            GATEWAY_TIMEOUT_CONFIDENCE,
            "No decline_code on the failure signal — classified as a gateway "
            "timeout (§3.2.3).",
        )

    # Step 2 — decline-code lookup.
    category, confidence = categorise(decline_code)
    code = _PAYMENT_BY_CATEGORY[category]
    reasoning = (
        f"Decline code {decline_code!r} classified as {category.name} "
        f"(§3.2.2, confidence {confidence})."
    )
    return _finish_payment(code, confidence, reasoning)


def classify_subscription_failure(
    *,
    mandate_type: MandateType,
    network_directive_tier: MacTier | None,
    decline_code: str | None,
    clearing_cycle_status: ClearingCycleStatus | None,
    mandate_cancelled_at: datetime | None,
) -> DiagnosisResult:
    """§3.2 steps 1–4 for SUBSCRIPTION_FAILURE.

    The §3.2.4 mandate-type facts (NACH still clearing; UPI AutoPay cap
    exhausted) are checked FIRST: they are "facts, not inferences" (confidence
    1.0), rail-specific, and terminal — they outrank a decline-code guess. They
    never collide with a card network directive, since a UPI/NACH mandate carries
    no Mastercard/Visa MAC tier.
    """
    # Step 4 (facts) — highest precedence.
    if (
        mandate_type is MandateType.NACH
        and clearing_cycle_status is ClearingCycleStatus.PENDING_CLEARING
    ):
        return _finish_subscription(
            RootCauseCode.NACH_CLEARING_PENDING,
            MANDATE_FACT_CONFIDENCE,
            "NACH presentment is still in the batch clearing cycle "
            "(clearing_cycle_status=PENDING_CLEARING) — not actually failed yet "
            "(§3.2.4, a fact not an inference).",
        )
    if mandate_type is MandateType.UPI_AUTOPAY and mandate_cancelled_at is not None:
        return _finish_subscription(
            RootCauseCode.UPI_AUTOPAY_CAP_EXHAUSTED,
            MANDATE_FACT_CONFIDENCE,
            "UPI AutoPay mandate cancelled post-cap by NPCI "
            f"(mandate_cancelled_at={mandate_cancelled_at.isoformat()}) — retry cap "
            "exhausted (§3.2.4, a fact not an inference).",
        )

    # Step 1 — network directive precedence (card mandates only, in practice).
    if network_directive_tier is MacTier.TIER_1_HARD_STOP:
        return _finish_subscription(
            RootCauseCode.MANDATE_CANCELLED_BY_CUSTOMER,
            NETWORK_DIRECTIVE_CONFIDENCE,
            "TIER_1_HARD_STOP network directive (e.g. MAC 21, stop-recurring) — "
            "mandate cancelled by the customer (§3.2.1).",
        )
    if network_directive_tier is MacTier.TIER_3_INSTRUMENT_DEAD:
        return _finish_subscription(
            RootCauseCode.INSTRUMENT_NOT_RECURRING_CAPABLE,
            NETWORK_DIRECTIVE_CONFIDENCE,
            "TIER_3_INSTRUMENT_DEAD network directive — the instrument cannot "
            "support recurring charges (§3.2.1).",
        )

    # Step 3 — missing decline_code. Subscription has no GATEWAY_TIMEOUT code;
    # an absent code is a genuinely unknown failure at the §3.2.3 confidence.
    if not decline_code:
        return _finish_subscription(
            RootCauseCode.UNKNOWN_SUBSCRIPTION_FAILURE,
            GATEWAY_TIMEOUT_CONFIDENCE,
            "No decline_code on the failed charge — unknown subscription failure "
            "at gateway-timeout confidence (§3.2.3).",
        )

    # Step 2 — decline-code lookup, mapped to the subscription vocabulary.
    category, confidence = categorise(decline_code)
    code = _SUBSCRIPTION_BY_CATEGORY[category]
    reasoning = (
        f"Decline code {decline_code!r} classified as {category.name} "
        f"(§3.2.2, confidence {confidence})."
    )
    return _finish_subscription(code, confidence, reasoning)


# --- CHECKOUT_ABANDONMENT ----------------------------------------------------


def classify_checkout_abandonment(
    *, drop_stage: str, payment_method_attempted: PaymentMethodAttempted
) -> DiagnosisResult:
    """§3.2 checkout: classify by `(drop_stage, payment_method_attempted)`.

    Confidence bands are kept honestly low — every checkout verdict is below
    `T = 0.65`, so checkout cases route to human review by construction. Torque
    has no storefront analytics to disambiguate intent from payment-layer signals
    alone (a limit this project's own competitive analysis names repeatedly).
    """
    stage = (drop_stage or "").strip().lower()
    pm = PaymentMethodAttempted(payment_method_attempted)

    if pm is PaymentMethodAttempted.NONE:
        return DiagnosisResult(
            RootCauseCode.NO_PAYMENT_METHOD_ATTEMPTED,
            CHECKOUT_NO_METHOD_CONFIDENCE,
            "No payment method was attempted — genuinely ambiguous (price, "
            "shipping, or just browsing); no storefront analytics to disambiguate.",
        )
    if pm is PaymentMethodAttempted.UPI_COLLECT:
        return DiagnosisResult(
            RootCauseCode.UPI_COLLECT_FRICTION,
            CHECKOUT_UPI_COLLECT_CONFIDENCE,
            "UPI Collect attempted and abandoned (drop_stage="
            f"{drop_stage!r}) — VPA-entry friction; recommend UPI Intent flow.",
        )
    if pm is PaymentMethodAttempted.CARD and any(
        tok in stage for tok in ("auth", "3ds", "otp")
    ):
        return DiagnosisResult(
            RootCauseCode.AUTH_3DS_TIMEOUT,
            CHECKOUT_AUTH_3DS_CONFIDENCE,
            f"Card attempted and abandoned at authentication (drop_stage={drop_stage!r}) "
            "— probable 3DS/OTP timeout.",
        )
    if pm in (
        PaymentMethodAttempted.CARD,
        PaymentMethodAttempted.NETBANKING,
        PaymentMethodAttempted.UPI_INTENT,
        PaymentMethodAttempted.BNPL,
    ):
        return DiagnosisResult(
            RootCauseCode.PAYMENT_METHOD_FAILED_MIDFLOW,
            CHECKOUT_MIDFLOW_CONFIDENCE,
            f"{pm.value} attempted and abandoned mid-flow (drop_stage={drop_stage!r}) "
            "— usually caught by §2.4 merge into the payment-failure case instead.",
        )
    return DiagnosisResult(
        RootCauseCode.UNKNOWN_ABANDONMENT,
        CHECKOUT_UNKNOWN_CONFIDENCE,
        f"Abandonment with method {pm.value}, drop_stage={drop_stage!r} — cause "
        "cannot be inferred from payment-layer signals alone.",
    )


# --- B2B_RECEIVABLE ----------------------------------------------------------


def classify_b2b_receivable(
    *,
    days_overdue: int | None,
    promise_keeping_rate: float | None,
    prior_invoice_count: int,
) -> DiagnosisResult:
    """§3.2 B2B: risk bucket from `days_overdue × promise_keeping_rate` where
    available. Confidence `0.8` for an established counterparty (3+ invoices on
    record), `0.4` cold-start — "no penalizing the diagnosis for lacking data it
    was never going to have" (§3.2).

    Bucketing thresholds are demo-scope (Module 3 owns refinement). Risk rises
    with `days_overdue` and falls with `promise_keeping_rate`; prolonged
    non-payment past `B2B_DISPUTE_DAYS_OVERDUE` is the coarse `DISPUTE_SUSPECTED`
    fallback (Torque has no dispute-flagging integration).
    """
    established = prior_invoice_count >= 3 and promise_keeping_rate is not None

    if not established:
        if days_overdue is None:
            return DiagnosisResult(
                RootCauseCode.UNKNOWN_RECEIVABLE_RISK,
                B2B_COLDSTART_CONFIDENCE,
                "Cold-start counterparty (fewer than 3 invoices on record) and no "
                "days-overdue signal — receivable risk unknown (§3.2).",
            )
        high = days_overdue >= B2B_COLDSTART_HIGH_RISK_DAYS
        code = (
            RootCauseCode.LIQUIDITY_DELAY_HIGH_RISK
            if high
            else RootCauseCode.LIQUIDITY_DELAY_LOW_RISK
        )
        return DiagnosisResult(
            code,
            B2B_COLDSTART_CONFIDENCE,
            f"Cold-start counterparty, {days_overdue}d overdue — bucketed on "
            "days-overdue alone at cold-start confidence (§3.2).",
        )

    # Established counterparty — full signal.
    assert promise_keeping_rate is not None  # narrowed by `established`
    if days_overdue is not None and days_overdue >= B2B_DISPUTE_DAYS_OVERDUE:
        return DiagnosisResult(
            RootCauseCode.DISPUTE_SUSPECTED,
            B2B_ESTABLISHED_CONFIDENCE,
            f"{days_overdue}d overdue for an established counterparty — beyond "
            "liquidity-delay range; dispute suspected (coarse fallback, §3.2).",
        )
    overdue = days_overdue or 0
    risk_score = overdue * (1.0 - promise_keeping_rate)
    high = risk_score >= B2B_HIGH_RISK_SCORE
    code = (
        RootCauseCode.LIQUIDITY_DELAY_HIGH_RISK
        if high
        else RootCauseCode.LIQUIDITY_DELAY_LOW_RISK
    )
    return DiagnosisResult(
        code,
        B2B_ESTABLISHED_CONFIDENCE,
        f"{overdue}d overdue × (1 − promise_keeping_rate {promise_keeping_rate:.2f}) "
        f"= risk score {risk_score:.1f} — "
        f"{'high' if high else 'low'}-risk liquidity delay (§3.2).",
    )
