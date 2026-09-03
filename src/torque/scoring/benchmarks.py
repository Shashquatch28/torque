"""Cold-start probability + warm-start adjustment — Blueprint Module 8 §8.1
(the operative algorithm behind Decision F).

`probability = lookup(leg_type, amount_bucket, days_since_failure)` implemented as
a **live, queryable function** over the exact benchmark table locked in Decision F:

| leg | bucket | probability |
|---|---|---|
| `SUBSCRIPTION_FAILURE` | 0–48h | 0.65 |
| | 3–7d  | 0.45 |
| | 7d+   | 0.25 |
| `PAYMENT_DEGRADATION` | same-session | 0.55 |
| `CHECKOUT_ABANDONMENT` | same-session | 0.40 |
| `B2B_RECEIVABLE` | 0–30d overdue | 0.35 |
| | 30–90d | 0.20 |
| | 90d+   | 0.12 |

**No alternative benchmark probabilities are invented.** These eight numbers are
transcribed verbatim from Decision F / Blueprint §8.1.

**`amount_bucket`** is part of the lookup signature (Decision F names it
"leg-type × amount-bucket × days-since-failure") but Decision F seeds **no
amount-tier variation** in the probabilities — every seeded value is
leg × time only. The dimension is therefore retained in the signature and
surfaced in the score breakdown (a grouping label for the future dashboard and
the learned-model feature set, §8.4) but it does **not** move the probability
today. See D-110.

**Boundary handling (explicit, tested):**

* Subscription `days_since_failure` is measured in **hours** for the first cut
  (`<= 48h` → 0.65) and **days** thereafter (`<= 7d` → 0.45, else 0.25). The
  48h–72h gap in Decision F's *labels* ("0–48h" then "3–7d") is resolved into
  the middle bucket — the operative rule is "fresh (≤48h) / aging (≤7d) / stale
  (>7d)", contiguous with no unhandled gap.
* B2B is bucketed on **days overdue**: `<= 30` → 0.35, `<= 90` → 0.20, else 0.12.
* Payment degradation and checkout abandonment have a single bucket each; the
  time input does not change the probability.

**Warm-start adjustment (§8.2 / D-110).** Where relationship history exists
(`Merchant_Counterparty.promise_keeping_rate is not None`):

    adjusted = base_probability × multiplier
    multiplier = cap_low + promise_keeping_rate × (cap_high − cap_low)   # linear map
               then clamped to [cap_low, cap_high]

with `cap_low` / `cap_high` from `PolicyConfig.warm_start_cap_low/high`
(default 0.5 / 1.3, Part E item 12). A `promise_keeping_rate` of ≈0.625 is the
break-even (×1.0); 0.0 → ×0.5 (exact lower cap); 1.0 → ×1.3 (exact upper cap).
An out-of-range stored rate is still clamped into the cap band. With no history
the multiplier is exactly 1.0 (`base` is used unchanged). The final probability
is clamped to `[0, 1]` and quantised — bounded and deterministic.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from torque.config import get_policy
from torque.enums import LegType

# --- Decision F cold-start table (verbatim) --------------------------------

_SUBSCRIPTION_FRESH = Decimal("0.65")   # 0–48h
_SUBSCRIPTION_AGING = Decimal("0.45")   # 3–7d
_SUBSCRIPTION_STALE = Decimal("0.25")   # 7d+
_PAYMENT_SAME_SESSION = Decimal("0.55")
_CHECKOUT_SAME_SESSION = Decimal("0.40")
_B2B_0_30 = Decimal("0.35")
_B2B_30_90 = Decimal("0.20")
_B2B_90_PLUS = Decimal("0.12")

#: Bucket-boundary constants (also the values the boundary tests pin).
SUBSCRIPTION_FRESH_MAX_HOURS = Decimal("48")
SUBSCRIPTION_AGING_MAX_DAYS = Decimal("7")
B2B_FRESH_MAX_DAYS = Decimal("30")
B2B_AGING_MAX_DAYS = Decimal("90")

_PROB_QUANT = Decimal("0.00001")
_ZERO = Decimal("0")
_ONE = Decimal("1")

# --- amount_bucket (grouping label only — no probability effect, D-110) ----

#: ₹ thresholds for the informational `amount_bucket` label. NOT from the
#: blueprint (Decision F seeds no amount tiers); used only for dashboard
#: grouping / the §8.4 feature set. Changing these does not change any score.
AMOUNT_BUCKET_SMALL_MAX = Decimal("1000")
AMOUNT_BUCKET_MEDIUM_MAX = Decimal("25000")


def amount_bucket(amount_at_risk: Decimal) -> str:
    """The informational size band for `amount_at_risk` (label only)."""
    amt = Decimal(str(amount_at_risk or 0))
    if amt <= AMOUNT_BUCKET_SMALL_MAX:
        return "SMALL"
    if amt <= AMOUNT_BUCKET_MEDIUM_MAX:
        return "MEDIUM"
    return "LARGE"


# --- cold-start lookup ----------------------------------------------------


def _quantize_prob(value: Decimal) -> Decimal:
    bounded = min(_ONE, max(_ZERO, value))
    return bounded.quantize(_PROB_QUANT, rounding=ROUND_HALF_EVEN)


def bucket_label(leg_type: LegType | str, days_since_failure: float | Decimal) -> str:
    """Human-readable bucket name for the score breakdown / "Why:" panel."""
    leg = LegType(leg_type)
    days = Decimal(str(days_since_failure))
    hours = days * 24
    if leg is LegType.SUBSCRIPTION_FAILURE:
        if hours <= SUBSCRIPTION_FRESH_MAX_HOURS:
            return "0-48h"
        if days <= SUBSCRIPTION_AGING_MAX_DAYS:
            return "3-7d"
        return "7d+"
    if leg is LegType.B2B_RECEIVABLE:
        if days <= B2B_FRESH_MAX_DAYS:
            return "0-30d overdue"
        if days <= B2B_AGING_MAX_DAYS:
            return "30-90d overdue"
        return "90d+ overdue"
    # payment degradation / checkout abandonment
    return "same-session"


def cold_start_probability(
    leg_type: LegType | str,
    days_since_failure: float | Decimal,
    *,
    amount_at_risk: Decimal | None = None,  # accepted for the signature; inert (D-110)
) -> Decimal:
    """`lookup(leg_type, amount_bucket, days_since_failure)` — the Decision F
    benchmark probability as an exact `Decimal`. `amount_at_risk` is part of the
    signature but does not affect the result (Decision F seeds no amount tiers)."""
    leg = LegType(leg_type)
    days = Decimal(str(days_since_failure))
    hours = days * 24

    if leg is LegType.SUBSCRIPTION_FAILURE:
        if hours <= SUBSCRIPTION_FRESH_MAX_HOURS:
            return _SUBSCRIPTION_FRESH
        if days <= SUBSCRIPTION_AGING_MAX_DAYS:
            return _SUBSCRIPTION_AGING
        return _SUBSCRIPTION_STALE
    if leg is LegType.PAYMENT_DEGRADATION:
        return _PAYMENT_SAME_SESSION
    if leg is LegType.CHECKOUT_ABANDONMENT:
        return _CHECKOUT_SAME_SESSION
    # B2B_RECEIVABLE
    if days <= B2B_FRESH_MAX_DAYS:
        return _B2B_0_30
    if days <= B2B_AGING_MAX_DAYS:
        return _B2B_30_90
    return _B2B_90_PLUS


# --- warm-start adjustment ----------------------------------------------


def warm_start_multiplier(promise_keeping_rate: float | None) -> Decimal:
    """The §8.2 multiplier for a `promise_keeping_rate` (or `None` → 1.0).

    Linear map onto `[cap_low, cap_high]`, then clamped so an out-of-range
    stored rate never escapes the cap band (D-110)."""
    if promise_keeping_rate is None:
        return _ONE
    policy = get_policy()
    low = Decimal(str(policy.warm_start_cap_low))
    high = Decimal(str(policy.warm_start_cap_high))
    rate = Decimal(str(promise_keeping_rate))
    raw = low + rate * (high - low)
    clamped = min(high, max(low, raw))
    return clamped.quantize(_PROB_QUANT, rounding=ROUND_HALF_EVEN)


def adjusted_probability(
    base_probability: Decimal, promise_keeping_rate: float | None
) -> Decimal:
    """`base × warm_start_multiplier`, clamped to [0, 1] and quantised."""
    multiplier = warm_start_multiplier(promise_keeping_rate)
    return _quantize_prob(Decimal(str(base_probability)) * multiplier)


__all__ = [
    "adjusted_probability",
    "amount_bucket",
    "bucket_label",
    "cold_start_probability",
    "warm_start_multiplier",
    "B2B_AGING_MAX_DAYS",
    "B2B_FRESH_MAX_DAYS",
    "SUBSCRIPTION_AGING_MAX_DAYS",
    "SUBSCRIPTION_FRESH_MAX_HOURS",
]
