"""Phase 7 — deterministic classification metrics + a majority-class
baseline comparison. Pure: no database, no I/O, operates only on the exact
labels/probabilities it is handed (the same "Absolute Data-Source Rule"
`torque.ai.evaluation` already documents for Phase 5 — never re-derives or
re-queries anything).

Every metric that is mathematically undefined for the given sample (most
commonly: ROC-AUC when the evaluation set contains only one true class) is
reported as `None`, never a fabricated/default number — the same honesty
convention `torque.ai.schemas.EvaluationReport` already established.
"""

from __future__ import annotations

from collections.abc import Sequence

from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

from torque.ai.shadow.schemas import ShadowClassificationMetrics


def compute_classification_metrics(
    y_true: Sequence[bool],
    y_pred_proba: Sequence[float],
    *,
    threshold: float = 0.5,
) -> ShadowClassificationMetrics:
    """Accuracy / precision / recall / F1 (all at `threshold`) + ROC-AUC
    (threshold-independent) over `(y_true, y_pred_proba)`. `len(y_true) ==
    len(y_pred_proba)` is required — a caller mismatch is a programming
    error, not a data-quality question this function is meant to absorb.
    """
    if len(y_true) != len(y_pred_proba):
        raise ValueError(
            f"y_true has {len(y_true)} entries but y_pred_proba has {len(y_pred_proba)}"
        )
    n = len(y_true)
    if n == 0:
        return ShadowClassificationMetrics(
            n_examples=0,
            accuracy=None,
            precision=None,
            recall=None,
            f1=None,
            roc_auc=None,
            positive_rate=0.0,
        )

    y_true_int = [1 if v else 0 for v in y_true]
    y_pred_int = [1 if p >= threshold else 0 for p in y_pred_proba]
    positive_rate = sum(y_true_int) / n

    roc_auc: float | None = None
    if len(set(y_true_int)) == 2:
        roc_auc = float(roc_auc_score(y_true_int, y_pred_proba))

    return ShadowClassificationMetrics(
        n_examples=n,
        accuracy=float(accuracy_score(y_true_int, y_pred_int)),
        precision=float(precision_score(y_true_int, y_pred_int, zero_division=0)),
        recall=float(recall_score(y_true_int, y_pred_int, zero_division=0)),
        f1=float(f1_score(y_true_int, y_pred_int, zero_division=0)),
        roc_auc=roc_auc,
        positive_rate=positive_rate,
    )


def majority_class_baseline_proba(train_labels: Sequence[bool], *, n: int) -> list[float]:
    """The trivial "always predict the training set's majority class" baseline,
    expressed as a constant probability (the training set's own positive
    rate) repeated `n` times — a fair, standard reference point Phase 7's
    task instructions explicitly require ("do not report impressive-looking
    metrics without checking ... baseline performance")."""
    if not train_labels:
        raise ValueError("cannot derive a majority-class baseline from zero training labels")
    positive_rate = sum(1 for v in train_labels if v) / len(train_labels)
    majority_proba = 1.0 if positive_rate >= 0.5 else 0.0
    return [majority_proba] * n


__all__ = ["compute_classification_metrics", "majority_class_baseline_proba"]
