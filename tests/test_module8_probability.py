"""Module 8 §8.1 / §8.2 — the cold-start benchmark lookup and the warm-start
adjustment. Pure functions over `torque.scoring.benchmarks`; no DB.

Every probability here is one of the eight numbers locked in Decision F —
nothing is invented. Bucket boundaries are pinned explicitly.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from torque.enums import LegType
from torque.scoring import benchmarks as B

# --- cold-start: the Decision F table, verbatim -------------------------


@pytest.mark.parametrize(
    ("leg", "days", "expected"),
    [
        # Subscription failure
        (LegType.SUBSCRIPTION_FAILURE, 0.0, "0.65"),
        (LegType.SUBSCRIPTION_FAILURE, 1.0, "0.65"),      # 24h, inside 0–48h
        (LegType.SUBSCRIPTION_FAILURE, 2.0, "0.65"),      # exactly 48h
        (LegType.SUBSCRIPTION_FAILURE, 5.0, "0.45"),      # 3–7d
        (LegType.SUBSCRIPTION_FAILURE, 7.0, "0.45"),      # exactly 7d
        (LegType.SUBSCRIPTION_FAILURE, 30.0, "0.25"),     # 7d+
        # Payment degradation — one bucket, time-independent
        (LegType.PAYMENT_DEGRADATION, 0.0, "0.55"),
        (LegType.PAYMENT_DEGRADATION, 90.0, "0.55"),
        # Checkout abandonment — one bucket, time-independent
        (LegType.CHECKOUT_ABANDONMENT, 0.0, "0.40"),
        (LegType.CHECKOUT_ABANDONMENT, 45.0, "0.40"),
        # B2B invoice (days overdue)
        (LegType.B2B_RECEIVABLE, 0.0, "0.35"),
        (LegType.B2B_RECEIVABLE, 30.0, "0.35"),           # exactly 30d
        (LegType.B2B_RECEIVABLE, 60.0, "0.20"),           # 30–90d
        (LegType.B2B_RECEIVABLE, 90.0, "0.20"),           # exactly 90d
        (LegType.B2B_RECEIVABLE, 120.0, "0.12"),          # 90d+
    ],
)
def test_cold_start_matches_decision_f(leg, days, expected):
    got = B.cold_start_probability(leg, days)
    assert got == Decimal(expected)
    assert isinstance(got, Decimal)  # exact, not float


@pytest.mark.parametrize(
    ("leg", "days", "expected"),
    [
        # Subscription 48h boundary: <= 48h is fresh, just over is aging.
        (LegType.SUBSCRIPTION_FAILURE, 47.99 / 24, "0.65"),
        (LegType.SUBSCRIPTION_FAILURE, 48.0 / 24, "0.65"),
        (LegType.SUBSCRIPTION_FAILURE, 48.01 / 24, "0.45"),
        # Subscription 7d boundary.
        (LegType.SUBSCRIPTION_FAILURE, 7.0, "0.45"),
        (LegType.SUBSCRIPTION_FAILURE, 7.0 + 1e-6, "0.25"),
        # B2B 30d boundary.
        (LegType.B2B_RECEIVABLE, 30.0, "0.35"),
        (LegType.B2B_RECEIVABLE, 30.0 + 1e-6, "0.20"),
        # B2B 90d boundary.
        (LegType.B2B_RECEIVABLE, 90.0, "0.20"),
        (LegType.B2B_RECEIVABLE, 90.0 + 1e-6, "0.12"),
    ],
)
def test_cold_start_bucket_boundaries(leg, days, expected):
    assert B.cold_start_probability(leg, days) == Decimal(expected)


def test_cold_start_gap_between_48h_and_3d_resolves_to_aging_bucket():
    # Decision F's *labels* jump from "0–48h" to "3–7d"; the operative rule fills
    # the 2–3 day gap with the aging (0.45) bucket — no unhandled range.
    for days in (2.1, 2.5, 2.99):
        assert B.cold_start_probability(LegType.SUBSCRIPTION_FAILURE, days) == Decimal("0.45")


def test_amount_at_risk_is_inert_in_the_lookup():
    # Decision F seeds no amount-tier variation (D-110). Same bucket, wildly
    # different amounts → identical probability.
    tiny = B.cold_start_probability(LegType.SUBSCRIPTION_FAILURE, 1.0, amount_at_risk=Decimal("1"))
    huge = B.cold_start_probability(
        LegType.SUBSCRIPTION_FAILURE, 1.0, amount_at_risk=Decimal("50000000")
    )
    assert tiny == huge == Decimal("0.65")


@pytest.mark.parametrize(
    ("leg", "days", "label"),
    [
        (LegType.SUBSCRIPTION_FAILURE, 1.0, "0-48h"),
        (LegType.SUBSCRIPTION_FAILURE, 5.0, "3-7d"),
        (LegType.SUBSCRIPTION_FAILURE, 20.0, "7d+"),
        (LegType.PAYMENT_DEGRADATION, 0.0, "same-session"),
        (LegType.CHECKOUT_ABANDONMENT, 0.0, "same-session"),
        (LegType.B2B_RECEIVABLE, 10.0, "0-30d overdue"),
        (LegType.B2B_RECEIVABLE, 45.0, "30-90d overdue"),
        (LegType.B2B_RECEIVABLE, 200.0, "90d+ overdue"),
    ],
)
def test_bucket_label(leg, days, label):
    assert B.bucket_label(leg, days) == label


@pytest.mark.parametrize(
    ("amount", "bucket"),
    [
        ("0", "SMALL"),
        ("999.99", "SMALL"),
        ("1000", "SMALL"),          # boundary — inclusive of SMALL
        ("1000.01", "MEDIUM"),
        ("25000", "MEDIUM"),        # boundary — inclusive of MEDIUM
        ("25000.01", "LARGE"),
        ("999999", "LARGE"),
    ],
)
def test_amount_bucket_label_boundaries(amount, bucket):
    assert B.amount_bucket(Decimal(amount)) == bucket


# --- warm-start adjustment (§8.2 / D-110) ------------------------------


def test_no_history_multiplier_is_exactly_one():
    assert B.warm_start_multiplier(None) == Decimal("1")


@pytest.mark.parametrize(
    ("rate", "multiplier"),
    [
        (0.0, "0.5"),       # exact LOWER cap
        (1.0, "1.3"),       # exact UPPER cap
        (0.625, "1.0"),     # break-even (0.5 + 0.625*0.8)
        (0.25, "0.7"),      # poor history
        (0.9, "1.22"),      # strong history (0.5 + 0.9*0.8)
    ],
)
def test_warm_start_multiplier_linear_map(rate, multiplier):
    assert B.warm_start_multiplier(rate) == Decimal(multiplier)


@pytest.mark.parametrize("rate", [2.0, 5.0, 1.0001])
def test_warm_start_multiplier_clamps_above_upper_cap(rate):
    assert B.warm_start_multiplier(rate) == Decimal("1.3")


@pytest.mark.parametrize("rate", [-1.0, -0.01])
def test_warm_start_multiplier_clamps_below_lower_cap(rate):
    assert B.warm_start_multiplier(rate) == Decimal("0.5")


def test_adjusted_probability_exact_decimal_arithmetic():
    # base 0.65 (subscription fresh) × 0.5 (rate 0.0) = 0.325 exactly.
    assert B.adjusted_probability(Decimal("0.65"), 0.0) == Decimal("0.325")
    # base 0.35 (B2B fresh) × 1.3 (rate 1.0) = 0.455 exactly.
    assert B.adjusted_probability(Decimal("0.35"), 1.0) == Decimal("0.455")


def test_adjusted_probability_is_bounded_and_deterministic():
    # Even the most generous case cannot exceed 1.0.
    hi = B.adjusted_probability(Decimal("0.65"), 1.0)   # 0.65 * 1.3 = 0.845
    assert Decimal("0") <= hi <= Decimal("1")
    # Deterministic — same inputs, same output.
    assert B.adjusted_probability(Decimal("0.45"), 0.4) == B.adjusted_probability(
        Decimal("0.45"), 0.4
    )


def test_strong_history_lifts_and_poor_history_drops_relative_to_base():
    base = Decimal("0.45")
    assert B.adjusted_probability(base, 0.95) > base
    assert B.adjusted_probability(base, 0.1) < base
    assert B.adjusted_probability(base, 0.625) == base  # neutral
