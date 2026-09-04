"""Phase 7 — `torque.ai.shadow.evaluation` correctness. Pure."""

from __future__ import annotations

import pytest

from torque.ai.shadow.evaluation import (
    compute_classification_metrics,
    majority_class_baseline_proba,
)


def test_compute_classification_metrics_hand_computed_example():
    # 4 examples: 2 true positives caught, 1 false negative, 1 true negative.
    y_true = [True, True, True, False]
    y_pred_proba = [0.9, 0.8, 0.2, 0.1]  # third case missed (below 0.5)

    metrics = compute_classification_metrics(y_true, y_pred_proba)

    assert metrics.n_examples == 4
    assert metrics.positive_rate == pytest.approx(0.75)
    assert metrics.accuracy == pytest.approx(0.75)  # 3/4 correct
    assert metrics.precision == pytest.approx(1.0)  # both predicted-positive are correct
    assert metrics.recall == pytest.approx(2 / 3)  # 2 of 3 true positives caught
    assert metrics.roc_auc is not None


def test_compute_classification_metrics_empty_input():
    metrics = compute_classification_metrics([], [])
    assert metrics.n_examples == 0
    assert metrics.accuracy is None
    assert metrics.roc_auc is None
    assert metrics.positive_rate == 0.0


def test_compute_classification_metrics_single_class_has_no_roc_auc():
    metrics = compute_classification_metrics([True, True, True], [0.9, 0.8, 0.6])
    assert metrics.roc_auc is None
    assert metrics.accuracy == pytest.approx(1.0)


def test_compute_classification_metrics_rejects_length_mismatch():
    with pytest.raises(ValueError):
        compute_classification_metrics([True, False], [0.5])


def test_majority_class_baseline_proba_reflects_training_majority():
    train_labels = [True, True, True, False]  # 75% positive
    baseline = majority_class_baseline_proba(train_labels, n=3)
    assert baseline == [1.0, 1.0, 1.0]


def test_majority_class_baseline_proba_negative_majority():
    train_labels = [True, False, False]
    baseline = majority_class_baseline_proba(train_labels, n=2)
    assert baseline == [0.0, 0.0]


def test_majority_class_baseline_proba_rejects_empty_training_labels():
    with pytest.raises(ValueError):
        majority_class_baseline_proba([], n=3)
