"""Phase 7 — `torque.ai.shadow.model` correctness: training, reproducibility,
prediction bounds, and small/degenerate-dataset behavior. Pure — no
database involved anywhere in this file."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from torque.ai.exceptions import InsufficientTrainingDataError, ModelNotFittedError
from torque.ai.shadow.model import LogisticRegressionShadowModel
from torque.ai.shadow.schemas import ShadowFeatureVector, ShadowTrainingExample


def _example(
    *,
    label: bool,
    case_id="c1",
    leg_type="PAYMENT_DEGRADATION",
    root_cause_code="NSF_SOFT_DECLINE",
    diagnosis_confidence=0.8,
    amount_at_risk="1000.00",
    days_since_failure=1.0,
    promise_keeping_rate=0.5,
    risk_score=None,
    mandate_type=None,
    network_directive_tier=None,
) -> ShadowTrainingExample:
    return ShadowTrainingExample(
        features=ShadowFeatureVector(
            case_id=case_id,
            merchant_id="m1",
            as_of=datetime.now(UTC),
            leg_type=leg_type,
            root_cause_code=root_cause_code,
            diagnosis_confidence=diagnosis_confidence,
            amount_at_risk=amount_at_risk,
            days_since_failure=days_since_failure,
            promise_keeping_rate=promise_keeping_rate,
            risk_score=risk_score,
            mandate_type=mandate_type,
            network_directive_tier=network_directive_tier,
        ),
        label=label,
    )


def _mixed_examples(n_pos=6, n_neg=4) -> list[ShadowTrainingExample]:
    examples = []
    for i in range(n_pos):
        examples.append(
            _example(
                label=True,
                case_id=f"pos{i}",
                diagnosis_confidence=0.9,
                amount_at_risk=str(500 + i * 10),
                days_since_failure=1.0,
                promise_keeping_rate=0.9,
            )
        )
    for i in range(n_neg):
        examples.append(
            _example(
                label=False,
                case_id=f"neg{i}",
                diagnosis_confidence=0.2,
                amount_at_risk=str(5000 + i * 10),
                days_since_failure=20.0,
                promise_keeping_rate=0.1,
                root_cause_code="ISSUER_HARD_DECLINE",
            )
        )
    return examples


def test_fit_raises_on_zero_examples():
    model = LogisticRegressionShadowModel()
    with pytest.raises(InsufficientTrainingDataError):
        model.fit([])


def test_predict_proba_raises_before_fit():
    model = LogisticRegressionShadowModel()
    with pytest.raises(ModelNotFittedError):
        model.predict_proba(_example(label=True).features)


def test_fit_then_predict_returns_a_probability_in_bounds():
    model = LogisticRegressionShadowModel()
    model.fit(_mixed_examples())
    assert model.is_fitted
    proba = model.predict_proba(_example(label=True, case_id="new").features)
    assert 0.0 <= proba <= 1.0


def test_training_is_deterministic_and_reproducible():
    examples = _mixed_examples()
    query = _example(label=True, case_id="query").features

    model_a = LogisticRegressionShadowModel()
    model_a.fit(examples)
    model_b = LogisticRegressionShadowModel()
    model_b.fit(examples)

    assert model_a.predict_proba(query) == model_b.predict_proba(query)


def test_model_id_is_stable_and_independent_of_training_data():
    model_a = LogisticRegressionShadowModel()
    model_a.fit(_mixed_examples(n_pos=3, n_neg=3))
    model_b = LogisticRegressionShadowModel()
    model_b.fit(_mixed_examples(n_pos=6, n_neg=1))
    assert model_a.model_id() == model_b.model_id() == "sklearn-logistic-regression-v1"


def test_single_class_training_data_falls_back_to_constant_predictor():
    model = LogisticRegressionShadowModel()
    all_recovered = [
        _example(label=True, case_id=f"c{i}", diagnosis_confidence=0.5) for i in range(3)
    ]
    model.fit(all_recovered)
    assert model.is_fitted
    assert model.predict_proba(_example(label=True, case_id="new").features) == 1.0


def test_single_class_negative_training_data_predicts_zero():
    model = LogisticRegressionShadowModel()
    all_not_recovered = [
        _example(label=False, case_id=f"c{i}", diagnosis_confidence=0.1) for i in range(3)
    ]
    model.fit(all_not_recovered)
    assert model.predict_proba(_example(label=True, case_id="new").features) == 0.0


def test_unseen_categorical_value_at_predict_time_does_not_crash():
    model = LogisticRegressionShadowModel()
    model.fit(_mixed_examples())
    unseen = _example(
        label=True,
        case_id="unseen",
        root_cause_code="A_ROOT_CAUSE_NEVER_SEEN_IN_TRAINING",
        mandate_type="NACH",
        network_directive_tier="TIER_1_HARD_STOP",
    ).features
    proba = model.predict_proba(unseen)
    assert 0.0 <= proba <= 1.0


def test_missing_numeric_fields_are_imputed_and_flagged_not_crashing():
    model = LogisticRegressionShadowModel()
    examples = _mixed_examples()
    examples.append(
        _example(
            label=True,
            case_id="missing_risk",
            risk_score=None,
            promise_keeping_rate=None,
        )
    )
    model.fit(examples)
    proba = model.predict_proba(
        _example(label=True, case_id="q", risk_score=None, promise_keeping_rate=None).features
    )
    assert 0.0 <= proba <= 1.0


def test_n_training_examples_reflects_fit_call():
    model = LogisticRegressionShadowModel()
    examples = _mixed_examples(n_pos=4, n_neg=2)
    model.fit(examples)
    assert model.n_training_examples == 6
