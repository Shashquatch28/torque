"""Razorpay decline-code → semantic category lookup (Blueprint §3.2 step 2).

The classifier maps a raw `decline_code` (Razorpay `error_code`, stored verbatim
by Module 2 ingestion) onto a small semantic `DeclineCategory`, plus a base
confidence. Two per-leg maps then translate a category to the leg's own
`root_cause_code` (PAYMENT_DEGRADATION vs SUBSCRIPTION_FAILURE draw from
different §3.1 vocabularies for the same underlying cause).

**Confidence, per §3.2:**
* Known / documented codes → `0.75`.
* Ambiguous or bank-internal opaque codes (the well-established Indian-bank
  decline-code-opacity problem) → `0.4` — inside the §3.2 `0.35–0.5` band and
  deliberately below `T = 0.65`, so an opaque code routes to human review *by
  construction* rather than by guessing.

**Scope caveat (Decision M / Part E item 1):** the specific code strings below
are a demo-scope seed, matched case-insensitively on a normalised token. The
authoritative code→behaviour mapping for every string Razorpay's acquirers
actually emit is a Module 5 pre-production checklist item, exactly as the
`MacCodeRegistry` tier seed is. This table is intentionally small; anything not
listed falls through to `OPAQUE` (low confidence), which is the correct,
non-guessing default.
"""

from __future__ import annotations

from enum import Enum, auto

# Base confidences (§3.2).
KNOWN_CODE_CONFIDENCE = 0.75
OPAQUE_CODE_CONFIDENCE = 0.4


class DeclineCategory(Enum):
    """Leg-independent semantic bucket for a raw decline code."""

    NSF = auto()  # insufficient funds — soft, retry after payday
    CARD_EXPIRED = auto()  # expired / reissued card — hard
    FRAUD_OR_CANCELLED = auto()  # fraud / stolen / do-not-honour / cancelled — hard
    INSTRUMENT_DEAD = auto()  # structurally non-recurring instrument — hard
    GENERIC_SOFT = auto()  # documented but non-NSF soft/temporary decline
    OPAQUE = auto()  # unknown / bank-internal — low confidence, escalate


# Normalised token (lower-case, verbatim as it might arrive in `decline_code`) →
# category. Only the documented codes earn `KNOWN_CODE_CONFIDENCE`.
_KNOWN: dict[str, DeclineCategory] = {
    # NSF / insufficient funds
    "insufficient_funds": DeclineCategory.NSF,
    "not_sufficient_funds": DeclineCategory.NSF,
    "nsf": DeclineCategory.NSF,
    "low_balance": DeclineCategory.NSF,
    # Expired / reissued card
    "card_expired": DeclineCategory.CARD_EXPIRED,
    "expired_card": DeclineCategory.CARD_EXPIRED,
    "card_reissued": DeclineCategory.CARD_EXPIRED,
    # Fraud / cancelled / do-not-honour family
    "stolen_card": DeclineCategory.FRAUD_OR_CANCELLED,
    "lost_card": DeclineCategory.FRAUD_OR_CANCELLED,
    "fraud": DeclineCategory.FRAUD_OR_CANCELLED,
    "fraudulent": DeclineCategory.FRAUD_OR_CANCELLED,
    "pickup_card": DeclineCategory.FRAUD_OR_CANCELLED,
    "restricted_card": DeclineCategory.FRAUD_OR_CANCELLED,
    "mandate_cancelled": DeclineCategory.FRAUD_OR_CANCELLED,
    "payment_cancelled": DeclineCategory.FRAUD_OR_CANCELLED,
    # Structurally non-recurring instrument
    "recurring_not_supported": DeclineCategory.INSTRUMENT_DEAD,
    "instrument_not_recurring_capable": DeclineCategory.INSTRUMENT_DEAD,
    "card_not_eligible_recurring": DeclineCategory.INSTRUMENT_DEAD,
    # Documented non-NSF soft / temporary
    "issuer_declined": DeclineCategory.GENERIC_SOFT,
    "transaction_not_permitted": DeclineCategory.GENERIC_SOFT,
    "try_again_later": DeclineCategory.GENERIC_SOFT,
    "issuer_temporarily_unavailable": DeclineCategory.GENERIC_SOFT,
}

# A handful of common opaque codes are listed explicitly for readability; every
# unlisted code also resolves to OPAQUE (the fall-through default). "do not
# honour" is the canonical opaque Indian-bank decline (§3.2).
_KNOWN_OPAQUE: frozenset[str] = frozenset(
    {
        "do_not_honour",
        "do_not_honor",
        "bad_request_error",
        "gateway_error",
        "server_error",
        "payment_failed",
    }
)


def _normalise(decline_code: str) -> str:
    return decline_code.strip().lower().replace(" ", "_").replace("-", "_")


def categorise(decline_code: str | None) -> tuple[DeclineCategory, float]:
    """Map a raw `decline_code` to `(category, base_confidence)`.

    An empty / missing code is NOT this function's concern (the classifier
    handles that as the §3.2 step-3 gateway-timeout case before calling here);
    passing one returns `(OPAQUE, OPAQUE_CODE_CONFIDENCE)` defensively.
    """
    if not decline_code:
        return DeclineCategory.OPAQUE, OPAQUE_CODE_CONFIDENCE
    token = _normalise(decline_code)
    category = _KNOWN.get(token)
    if category is not None:
        return category, KNOWN_CODE_CONFIDENCE
    return DeclineCategory.OPAQUE, OPAQUE_CODE_CONFIDENCE
