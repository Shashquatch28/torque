"""Module 9b — the confidence-interval math (pure, no DB).

Wilson score interval per cohort proportion; Newcombe (1998) hybrid score
interval for the difference. Covers the edges the Blueprint calls out: zero
denominators, zero / all successes, one observation, tiny cohorts, equal rates,
negative and positive lift — never NaN / infinity / an out-of-range bound.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from torque.reporting.incrementality import (
    _CONFIDENCE_LEVEL,
    _Z,
    newcombe_difference,
    wilson_interval,
)

ZERO, ONE, NEG_ONE = Decimal(0), Decimal(1), Decimal(-1)


def _finite(*values: Decimal | None) -> None:
    for v in values:
        if v is None:
            continue
        assert v == v  # not NaN
        assert v.is_finite()


# --- Wilson single proportion ----------------------------------------


def test_confidence_level_and_z_are_the_documented_95pct() -> None:
    assert _CONFIDENCE_LEVEL == Decimal("0.95")
    assert Decimal("1.9599") < _Z < Decimal("1.9600")  # Φ⁻¹(0.975)


def test_zero_denominator_is_undefined_not_nan() -> None:
    assert wilson_interval(0, 0) == (None, None)


@pytest.mark.parametrize(
    "x,n",
    [(0, 1), (1, 1), (0, 3), (3, 3), (1, 3), (2, 5), (5, 13), (50, 100), (100, 100)],
)
def test_wilson_bounds_are_valid_probabilities_and_ordered(x: int, n: int) -> None:
    low, high = wilson_interval(x, n)
    _finite(low, high)
    assert ZERO <= low <= high <= ONE


def test_wilson_matches_the_textbook_value_for_p_half_n_100() -> None:
    # Wilson 95% CI for 50/100 is ≈ (0.4038, 0.5962).
    low, high = wilson_interval(50, 100)
    assert abs(low - Decimal("0.4038")) <= Decimal("0.0002")
    assert abs(high - Decimal("0.5962")) <= Decimal("0.0002")


def test_wilson_all_successes_upper_is_one_lower_below_one() -> None:
    low, high = wilson_interval(7, 7)
    assert high == ONE
    assert ZERO < low < ONE


def test_wilson_zero_successes_lower_is_zero_upper_above_zero() -> None:
    low, high = wilson_interval(0, 4)
    assert low == ZERO
    assert ZERO < high < ONE


def test_wilson_one_observation_still_valid() -> None:
    for x in (0, 1):
        low, high = wilson_interval(x, 1)
        _finite(low, high)
        assert ZERO <= low <= high <= ONE


# --- Newcombe difference (treatment − control) ----------------------


def test_difference_undefined_when_either_cohort_empty() -> None:
    assert newcombe_difference(3, 5, 0, 0) == (None, None)
    assert newcombe_difference(0, 0, 1, 4) == (None, None)
    assert newcombe_difference(0, 0, 0, 0) == (None, None)


@pytest.mark.parametrize(
    "tx,tn,cx,cn",
    [
        (5, 13, 1, 3),     # small, positive-ish lift
        (1, 2, 1, 2),      # equal rates
        (0, 10, 10, 10),   # maximally negative lift
        (10, 10, 0, 10),   # maximally positive lift
        (1, 1, 0, 1),      # one observation each
        (2, 3, 2, 3),      # equal, tiny
        (25, 50, 20, 50),  # moderate n
    ],
)
def test_difference_bounds_within_pm_one_and_ordered(
    tx: int, tn: int, cx: int, cn: int
) -> None:
    low, high = newcombe_difference(tx, tn, cx, cn)
    _finite(low, high)
    assert NEG_ONE <= low <= high <= ONE


def test_equal_rates_interval_is_symmetric_about_zero_and_contains_it() -> None:
    low, high = newcombe_difference(4, 8, 4, 8)
    assert low < ZERO < high
    assert abs(low + high) <= Decimal("0.0001")  # symmetric


def test_strongly_negative_lift_interval_stays_negative() -> None:
    low, high = newcombe_difference(0, 20, 20, 20)
    assert high < ZERO
    assert low == NEG_ONE  # clamped, not overflowed


def test_strongly_positive_lift_interval_stays_positive() -> None:
    low, high = newcombe_difference(20, 20, 0, 20)
    assert low > ZERO
    assert high == ONE
