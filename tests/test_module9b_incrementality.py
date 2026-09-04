"""Module 9b — headline lift and rate edge cases (real DB).

`incremental_lift = treatment_recovery_rate − control_recovery_rate`, recovery =
intent-to-treat `status ∈ {RECOVERED, CANCELLED}` (D-133). Every figure comes
from `RevenueLeakCase.control_group` / `status` / `opened_at`.
"""

from __future__ import annotations

from decimal import Decimal

from tests.module9b_helpers import (
    BEFORE_WINDOW,
    WINDOW_END,
    WINDOW_MID,
    WINDOW_START,
    cohort_case,
)
from torque.enums import CaseStatus, LegType
from torque.reporting import ReportWindow, incrementality_report

ZERO, ONE = Decimal(0), Decimal(1)


def _report(db, merchant, **kw):
    return incrementality_report(db, merchant.merchant_id, **kw)


# --- A. basic lift -------------------------------------------------


def test_treatment_above_control_positive_lift(db, make_merchant, make_case):
    m = make_merchant()
    for _ in range(3):
        cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, m, control=False, recovered=False)  # 3/4 treatment
    cohort_case(make_case, m, control=True, recovered=True)
    for _ in range(3):
        cohort_case(make_case, m, control=True, recovered=False)  # 1/4 control

    rep = _report(db, m)
    assert rep.treatment.successes == 3 and rep.treatment.total == 4
    assert rep.treatment.rate == Decimal("0.7500")
    assert rep.control.successes == 1 and rep.control.total == 4
    assert rep.control.rate == Decimal("0.2500")
    assert rep.lift.point == Decimal("0.5000")
    assert rep.lift.ci_low <= rep.lift.point <= rep.lift.ci_high


def test_equal_rates_zero_lift(db, make_merchant, make_case):
    m = make_merchant()
    for grp in (False, True):
        cohort_case(make_case, m, control=grp, recovered=True)
        cohort_case(make_case, m, control=grp, recovered=False)
    rep = _report(db, m)
    assert rep.treatment.rate == rep.control.rate == Decimal("0.5000")
    assert rep.lift.point == ZERO
    assert rep.lift.ci_low < ZERO < rep.lift.ci_high  # honest: can't rule out 0


def test_treatment_below_control_negative_lift(db, make_merchant, make_case):
    m = make_merchant()
    cohort_case(make_case, m, control=False, recovered=True)
    for _ in range(3):
        cohort_case(make_case, m, control=False, recovered=False)  # 1/4
    for _ in range(3):
        cohort_case(make_case, m, control=True, recovered=True)
    cohort_case(make_case, m, control=True, recovered=False)  # 3/4
    rep = _report(db, m)
    assert rep.lift.point == Decimal("-0.5000")
    assert rep.lift.ci_low >= Decimal("-1")


# --- B. rate edge cases -----------------------------------------


def test_zero_treatment_cases(db, make_merchant, make_case):
    m = make_merchant()
    cohort_case(make_case, m, control=True, recovered=True)
    rep = _report(db, m)
    assert rep.treatment.total == 0
    assert rep.treatment.rate is None
    assert rep.treatment.ci_low is None and rep.treatment.ci_high is None
    assert rep.lift.point is None and rep.lift.ci_low is None


def test_zero_control_cases(db, make_merchant, make_case):
    m = make_merchant()
    cohort_case(make_case, m, control=False, recovered=True)
    rep = _report(db, m)
    assert rep.control.total == 0 and rep.control.rate is None
    assert rep.lift.point is None


def test_empty_dataset_all_null_no_crash(db, make_merchant):
    m = make_merchant()
    rep = _report(db, m)
    assert rep.treatment.total == rep.control.total == 0
    assert rep.lift.point is None
    assert rep.sutva.lift.point is None
    assert rep.sutva.contaminated_control_counterparties == 0


def test_unassigned_cohort_cases_are_excluded(db, make_merchant, make_case):
    m = make_merchant()
    # control_group left NULL → neither arm
    make_case(merchant=m, status=CaseStatus.RECOVERED, opened_at=WINDOW_MID)
    cohort_case(make_case, m, control=False, recovered=True)
    rep = _report(db, m)
    assert rep.treatment.total == 1 and rep.control.total == 0


def test_zero_recovered_in_both_arms(db, make_merchant, make_case):
    m = make_merchant()
    for grp in (False, False, True, True):
        cohort_case(make_case, m, control=grp, recovered=False)
    rep = _report(db, m)
    assert rep.treatment.rate == ZERO and rep.control.rate == ZERO
    assert rep.lift.point == ZERO
    assert rep.treatment.ci_low == ZERO and rep.treatment.ci_high > ZERO


def test_all_recovered_in_both_arms(db, make_merchant, make_case):
    m = make_merchant()
    for grp in (False, False, True, True):
        cohort_case(make_case, m, control=grp, recovered=True)
    rep = _report(db, m)
    assert rep.treatment.rate == ONE and rep.control.rate == ONE
    assert rep.lift.point == ZERO
    assert rep.treatment.ci_high == ONE and rep.treatment.ci_low < ONE


def test_one_observation_per_arm(db, make_merchant, make_case):
    m = make_merchant()
    cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, m, control=True, recovered=False)
    rep = _report(db, m)
    assert rep.treatment.total == rep.control.total == 1
    assert rep.lift.point == Decimal("1.0000")
    assert Decimal("-1") <= rep.lift.ci_low <= rep.lift.ci_high <= ONE


def test_very_small_cohorts_bounds_stay_valid(db, make_merchant, make_case):
    m = make_merchant()
    cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, m, control=False, recovered=False)
    cohort_case(make_case, m, control=True, recovered=False)
    rep = _report(db, m)
    for ci in (rep.treatment, rep.control):
        assert ZERO <= ci.ci_low <= ci.ci_high <= ONE
    assert Decimal("-1") <= rep.lift.ci_low <= rep.lift.ci_high <= ONE


# --- recovery definition (D-133): CANCELLED counts, others don't ----


def test_cancelled_self_pay_counts_as_recovered(db, make_merchant, make_case):
    m = make_merchant()
    cohort_case(make_case, m, control=True, status=CaseStatus.CANCELLED)
    cohort_case(make_case, m, control=True, status=CaseStatus.EXHAUSTED)
    rep = _report(db, m)
    assert rep.control.successes == 1 and rep.control.total == 2


def test_partially_recovered_and_written_off_do_not_count(db, make_merchant, make_case):
    m = make_merchant()
    cohort_case(make_case, m, control=False, status=CaseStatus.PARTIALLY_RECOVERED,
                leg=LegType.B2B_RECEIVABLE)
    cohort_case(make_case, m, control=False, status=CaseStatus.WRITTEN_OFF)
    cohort_case(make_case, m, control=False, status=CaseStatus.RECOVERED)
    rep = _report(db, m)
    assert rep.treatment.successes == 1 and rep.treatment.total == 3


# --- window: opened_at half-open, Module 9 convention ---------------


def test_window_filters_on_opened_at(db, make_merchant, make_case):
    m = make_merchant()
    cohort_case(make_case, m, control=False, recovered=True, opened_at=WINDOW_MID)
    cohort_case(make_case, m, control=True, recovered=True, opened_at=BEFORE_WINDOW)
    rep = _report(db, m, window=ReportWindow(start=WINDOW_START, end=WINDOW_END))
    assert rep.treatment.total == 1
    assert rep.control.total == 0  # the control case opened before the window
    assert rep.opened_from == WINDOW_START and rep.opened_to == WINDOW_END
    assert rep.window_basis == "opened_at"


def test_leg_filter(db, make_merchant, make_case):
    m = make_merchant()
    cohort_case(make_case, m, control=False, recovered=True,
                leg=LegType.PAYMENT_DEGRADATION)
    cohort_case(make_case, m, control=False, recovered=True,
                leg=LegType.SUBSCRIPTION_FAILURE)
    rep = _report(db, m, leg=LegType.SUBSCRIPTION_FAILURE)
    assert rep.treatment.total == 1
    assert rep.leg_type == "SUBSCRIPTION_FAILURE"


def test_superseded_cases_excluded(db, make_merchant, make_case):
    m = make_merchant()
    keep = cohort_case(make_case, m, control=False, recovered=True)
    gone = cohort_case(make_case, m, control=False, recovered=True)
    gone.superseded_by_case_id = keep.case_id
    db.flush()
    rep = _report(db, m)
    assert rep.treatment.total == 1


def test_deterministic_repeated_calls(db, make_merchant, make_case):
    m = make_merchant()
    for grp in (False, False, True):
        cohort_case(make_case, m, control=grp, recovered=True)
    a = _report(db, m).model_dump()
    b = _report(db, m).model_dump()
    assert a == b
