"""Phase 7 — `torque.ai.shadow.training` correctness: temporal split
correctness, empty/small-dataset behavior, class-imbalance behavior,
baseline comparison, and — the top structural requirement — proof that
none of this ever mutates authoritative Torque state.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.ai_shadow_cases import make_terminal_diagnosed_case
from torque.ai.shadow.model import LogisticRegressionShadowModel
from torque.ai.shadow.schemas import ShadowTrainingExample
from torque.ai.shadow.training import (
    MIN_CASES_FOR_MEANINGFUL_EVALUATION,
    MIN_CASES_FOR_SPLIT,
    temporal_train_test_split,
    train_and_evaluate_shadow_model,
)
from torque.enums import CaseStatus


def _case_with_cutoff(db, make_case, *, status, diagnosed_hours_after_open, merchant):
    """A terminal, diagnosed case whose `as_of` cutoff is controlled purely
    by `diagnosed_hours_after_open` relative to a shared `opened_at`
    baseline — used to build a deterministically orderable sequence of
    examples for temporal-split tests."""
    return make_terminal_diagnosed_case(
        db,
        make_case,
        status=status,
        merchant=merchant,
        opened_days_ago=0.0,
        diagnosed_hours_after_open=diagnosed_hours_after_open,
    )


# --- empty / small dataset behavior -----------------------------------------


def test_zero_cases_reports_insufficient_data_honestly(db, make_merchant):
    merchant = make_merchant()
    report = train_and_evaluate_shadow_model(db, merchant_id=merchant.merchant_id)
    assert report.n_total_cases == 0
    assert report.n_train == 0
    assert report.n_test == 0
    assert report.insufficient_data is True
    assert report.test_metrics is None
    assert report.baseline_metrics is None
    assert report.limitations
    assert report.disclaimer


def test_below_split_threshold_trains_on_everything_with_no_held_out_set(
    db, make_case, make_merchant
):
    merchant = make_merchant()
    n = MIN_CASES_FOR_SPLIT - 1
    for i in range(n):
        _case_with_cutoff(
            db,
            make_case,
            status=CaseStatus.RECOVERED,
            diagnosed_hours_after_open=i,
            merchant=merchant,
        )

    report = train_and_evaluate_shadow_model(db, merchant_id=merchant.merchant_id)

    assert report.n_total_cases == n
    assert report.n_train == n
    assert report.n_test == 0
    assert report.insufficient_data is True
    assert report.test_metrics is None
    assert report.baseline_metrics is None
    assert any("too few" in note for note in report.limitations)


def test_below_meaningful_evaluation_threshold_still_evaluates_but_flags_it(
    db, make_case, make_merchant
):
    merchant = make_merchant()
    assert MIN_CASES_FOR_SPLIT < 10 < MIN_CASES_FOR_MEANINGFUL_EVALUATION
    for i in range(8):
        _case_with_cutoff(
            db,
            make_case,
            status=CaseStatus.RECOVERED,
            diagnosed_hours_after_open=i,
            merchant=merchant,
        )
    for i in range(2):
        _case_with_cutoff(
            db,
            make_case,
            status=CaseStatus.EXHAUSTED,
            diagnosed_hours_after_open=8 + i,
            merchant=merchant,
        )

    report = train_and_evaluate_shadow_model(db, merchant_id=merchant.merchant_id)

    assert report.n_total_cases == 10
    assert report.n_train + report.n_test == 10
    assert report.n_test >= 1
    assert report.insufficient_data is True
    assert report.test_metrics is not None
    assert report.baseline_metrics is not None
    assert any("rule-of-thumb" in note for note in report.limitations)


# --- temporal split correctness ---------------------------------------------


def test_temporal_split_puts_earliest_examples_in_train_and_latest_in_test():
    def ex(case_id, hours_offset, label):
        from datetime import UTC, datetime

        from torque.ai.shadow.schemas import ShadowFeatureVector

        return ShadowTrainingExample(
            features=ShadowFeatureVector(
                case_id=case_id,
                merchant_id="m1",
                as_of=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hours_offset),
                leg_type="PAYMENT_DEGRADATION",
                root_cause_code="X",
                diagnosis_confidence=0.5,
                amount_at_risk="100.00",
                days_since_failure=1.0,
                promise_keeping_rate=None,
                risk_score=None,
                mandate_type=None,
                network_directive_tier=None,
            ),
            label=label,
        )

    # Deliberately shuffled input order — the split must sort by `as_of`,
    # never rely on input ordering.
    examples = [
        ex("c3", 3, True),
        ex("c1", 1, True),
        ex("c5", 5, False),
        ex("c2", 2, True),
        ex("c4", 4, False),
    ]

    train, test = temporal_train_test_split(examples, test_fraction=0.4)

    assert [e.features.case_id for e in train] == ["c1", "c2", "c3"]
    assert [e.features.case_id for e in test] == ["c4", "c5"]


def test_temporal_split_always_leaves_at_least_one_train_example():
    from datetime import UTC, datetime

    from torque.ai.shadow.schemas import ShadowFeatureVector

    def ex(case_id, hours_offset):
        return ShadowTrainingExample(
            features=ShadowFeatureVector(
                case_id=case_id,
                merchant_id="m1",
                as_of=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hours_offset),
                leg_type="PAYMENT_DEGRADATION",
                root_cause_code="X",
                diagnosis_confidence=0.5,
                amount_at_risk="100.00",
                days_since_failure=1.0,
                promise_keeping_rate=None,
                risk_score=None,
                mandate_type=None,
                network_directive_tier=None,
            ),
            label=True,
        )

    examples = [ex("c1", 1), ex("c2", 2)]
    train, test = temporal_train_test_split(examples, test_fraction=0.9)
    assert len(train) == 1
    assert len(test) == 1


def test_temporal_split_rejects_out_of_range_fraction():
    with pytest.raises(ValueError):
        temporal_train_test_split([], test_fraction=0.0)
    with pytest.raises(ValueError):
        temporal_train_test_split([], test_fraction=1.0)


# --- class imbalance behavior + baseline comparison -------------------------


def test_class_distribution_and_baseline_reflect_real_imbalance(db, make_case, make_merchant):
    merchant = make_merchant()
    for i in range(9):
        _case_with_cutoff(
            db,
            make_case,
            status=CaseStatus.RECOVERED,
            diagnosed_hours_after_open=i,
            merchant=merchant,
        )
    for i in range(1):
        _case_with_cutoff(
            db,
            make_case,
            status=CaseStatus.EXHAUSTED,
            diagnosed_hours_after_open=9 + i,
            merchant=merchant,
        )

    report = train_and_evaluate_shadow_model(db, merchant_id=merchant.merchant_id)

    assert report.class_distribution == {"recovered": 9, "not_recovered": 1}
    # n_total=10, default test_fraction=0.2 -> n_test=2: the single negative
    # example (most-recently-diagnosed) plus the one positive just before it.
    assert report.n_test == 2
    assert report.test_metrics is not None
    assert report.test_metrics.positive_rate == pytest.approx(0.5)
    # The training split is entirely positive -> the majority-class baseline
    # always predicts "recovered", so it gets exactly the one true negative
    # in the test split wrong (50% accuracy on this 2-example test split).
    assert report.baseline_metrics is not None
    assert report.baseline_metrics.accuracy == pytest.approx(0.5)


def test_single_class_dataset_is_flagged_in_limitations(db, make_case, make_merchant):
    merchant = make_merchant()
    for i in range(6):
        _case_with_cutoff(
            db,
            make_case,
            status=CaseStatus.RECOVERED,
            diagnosed_hours_after_open=i,
            merchant=merchant,
        )

    report = train_and_evaluate_shadow_model(db, merchant_id=merchant.merchant_id)

    assert report.class_distribution == {"recovered": 6, "not_recovered": 0}
    assert any("only one outcome class" in note for note in report.limitations)


# --- no mutation of authoritative state -------------------------------------


def test_training_and_evaluation_writes_nothing_to_the_database(db, make_case, make_merchant):
    merchant = make_merchant()
    for i in range(8):
        _case_with_cutoff(
            db,
            make_case,
            status=CaseStatus.RECOVERED if i % 2 == 0 else CaseStatus.EXHAUSTED,
            diagnosed_hours_after_open=i,
            merchant=merchant,
        )
    db.flush()

    before_new, before_dirty, before_deleted = len(db.new), len(db.dirty), len(db.deleted)
    train_and_evaluate_shadow_model(db, merchant_id=merchant.merchant_id)
    assert len(db.new) == before_new
    assert len(db.dirty) == before_dirty
    assert len(db.deleted) == before_deleted


def test_default_model_factory_produces_a_fitted_logistic_regression_model(
    db, make_case, make_merchant
):
    merchant = make_merchant()
    for i in range(6):
        _case_with_cutoff(
            db,
            make_case,
            status=CaseStatus.RECOVERED if i < 4 else CaseStatus.EXHAUSTED,
            diagnosed_hours_after_open=i,
            merchant=merchant,
        )

    model = LogisticRegressionShadowModel()
    report = train_and_evaluate_shadow_model(
        db, merchant_id=merchant.merchant_id, model_factory=lambda: model
    )
    assert report.model_id == "sklearn-logistic-regression-v1"
    assert model.is_fitted
