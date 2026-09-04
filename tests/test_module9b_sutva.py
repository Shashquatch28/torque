"""Module 9b — SUTVA cross-merchant contamination adjustment (Blueprint §6).

A CONTROL counterparty for merchant M that is ALSO a TREATMENT counterparty for
another merchant, with an in-window case, is contaminated: its control
observations are dropped from the adjusted view. Treatment is never touched. The
headline lift is always preserved alongside.
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
from torque.reporting import ReportWindow, incrementality_report


def _rep(db, m, **kw):
    return incrementality_report(db, m.merchant_id, **kw)


def test_no_overlap_adjusted_equals_headline(db, make_merchant, make_case):
    m = make_merchant()
    for _ in range(2):
        cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, m, control=True, recovered=True)
    cohort_case(make_case, m, control=True, recovered=False)

    rep = _rep(db, m)
    assert rep.sutva.contaminated_control_counterparties == 0
    assert rep.sutva.excluded_control_cases == 0
    assert rep.sutva.control.model_dump() == rep.control.model_dump()
    assert rep.sutva.lift.model_dump() == rep.lift.model_dump()


def test_overlap_excludes_the_contaminated_control_counterparty(
    db, make_merchant, make_counterparty, make_case
):
    m, other = make_merchant(), make_merchant()
    shared = make_counterparty()

    # m: `shared` is control and (spuriously) recovered; plus a clean control miss
    cohort_case(make_case, m, control=True, recovered=True, counterparty=shared)
    cohort_case(make_case, m, control=True, recovered=False)
    cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, m, control=False, recovered=True)  # treatment 2/2

    # other merchant: `shared` is in TREATMENT, case opened in-window → contamination
    cohort_case(make_case, other, control=False, recovered=True, counterparty=shared)

    rep = _rep(db, m)
    # headline: control 1/2 = 0.5
    assert rep.control.successes == 1 and rep.control.total == 2
    assert rep.control.rate == Decimal("0.5000")
    # adjusted: the contaminated (recovered) control case is dropped → 0/1
    assert rep.sutva.contaminated_control_counterparties == 1
    assert rep.sutva.excluded_control_cases == 1
    assert rep.sutva.control.successes == 0 and rep.sutva.control.total == 1
    assert rep.sutva.control.rate == Decimal("0.0000")
    # → adjusted lift is higher than the headline (contamination was masking it)
    assert rep.sutva.lift.point > rep.lift.point
    # headline is preserved, not replaced
    assert rep.lift.point == Decimal("0.5000")


def test_counterparty_only_in_control_is_retained(
    db, make_merchant, make_counterparty, make_case
):
    m = make_merchant()
    cp = make_counterparty()
    cohort_case(make_case, m, control=True, recovered=True, counterparty=cp)
    cohort_case(make_case, m, control=False, recovered=True)
    rep = _rep(db, m)
    assert rep.sutva.contaminated_control_counterparties == 0
    assert rep.sutva.control.total == 1  # retained


def test_counterparty_only_in_treatment_elsewhere_does_not_touch_treatment(
    db, make_merchant, make_counterparty, make_case
):
    m, other = make_merchant(), make_merchant()
    shared = make_counterparty()
    # `shared` is TREATMENT at m and TREATMENT at other — no control involvement
    cohort_case(make_case, m, control=False, recovered=True, counterparty=shared)
    cohort_case(make_case, m, control=True, recovered=False)
    cohort_case(make_case, other, control=False, recovered=True, counterparty=shared)
    rep = _rep(db, m)
    # SUTVA only ever removes CONTROL counterparties; treatment is identical
    assert rep.sutva.contaminated_control_counterparties == 0
    assert rep.treatment.total == 1
    assert rep.sutva.control.model_dump() == rep.control.model_dump()
    assert rep.sutva.lift.model_dump() == rep.lift.model_dump()


def test_overlap_outside_the_window_is_not_contamination(
    db, make_merchant, make_counterparty, make_case
):
    m, other = make_merchant(), make_merchant()
    shared = make_counterparty()
    cohort_case(make_case, m, control=True, recovered=True, counterparty=shared,
                opened_at=WINDOW_MID)
    cohort_case(make_case, m, control=False, recovered=True, opened_at=WINDOW_MID)
    # other merchant's treatment case for `shared` is BEFORE the window
    cohort_case(make_case, other, control=False, recovered=True, counterparty=shared,
                opened_at=BEFORE_WINDOW)

    rep = _rep(db, m, window=ReportWindow(start=WINDOW_START, end=WINDOW_END))
    assert rep.sutva.contaminated_control_counterparties == 0
    assert rep.sutva.control.model_dump() == rep.control.model_dump()


def test_multiple_merchants_multiple_overlaps(
    db, make_merchant, make_counterparty, make_case
):
    m, n1, n2 = make_merchant(), make_merchant(), make_merchant()
    a, b, c = make_counterparty(), make_counterparty(), make_counterparty()

    # m control cohort: a, b, c  (a & b will be contaminated, c stays clean)
    cohort_case(make_case, m, control=True, recovered=True, counterparty=a)
    cohort_case(make_case, m, control=True, recovered=True, counterparty=b)
    cohort_case(make_case, m, control=True, recovered=False, counterparty=c)
    # m treatment cohort
    for _ in range(3):
        cohort_case(make_case, m, control=False, recovered=True)

    cohort_case(make_case, n1, control=False, recovered=True, counterparty=a)
    cohort_case(make_case, n2, control=False, recovered=True, counterparty=b)

    rep = _rep(db, m)
    assert rep.control.total == 3 and rep.control.successes == 2  # 0.6667
    assert rep.sutva.contaminated_control_counterparties == 2
    assert rep.sutva.excluded_control_cases == 2
    assert rep.sutva.control.total == 1 and rep.sutva.control.successes == 0


def test_control_at_another_merchant_is_not_contamination(
    db, make_merchant, make_counterparty, make_case
):
    """Only a TREATMENT case elsewhere contaminates — a control case elsewhere
    does not."""
    m, other = make_merchant(), make_merchant()
    shared = make_counterparty()
    cohort_case(make_case, m, control=True, recovered=True, counterparty=shared)
    cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, other, control=True, recovered=True, counterparty=shared)
    rep = _rep(db, m)
    assert rep.sutva.contaminated_control_counterparties == 0


def test_headline_and_adjusted_lift_both_present_and_labelled(
    db, make_merchant, make_counterparty, make_case
):
    m, other = make_merchant(), make_merchant()
    shared = make_counterparty()
    cohort_case(make_case, m, control=True, recovered=True, counterparty=shared)
    cohort_case(make_case, m, control=True, recovered=False)
    cohort_case(make_case, m, control=False, recovered=True)
    cohort_case(make_case, other, control=False, recovered=True, counterparty=shared)

    rep = _rep(db, m)
    assert rep.lift.point is not None            # headline preserved
    assert rep.sutva.lift.point is not None      # adjusted present, separate
    assert rep.sutva.note and "spillover" in rep.sutva.note.lower()
    assert rep.recovery_definition
