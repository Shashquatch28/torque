"""Phase 7 — the replaceable shadow-model interface + the one baseline
implementation. Pure: no database, no I/O, no network call, no GPU.

    feature vectors (torque.ai.shadow.features)
            v
    ShadowModel.fit(examples)
            v
    ShadowModel.predict_proba(features) -> float in [0, 1]

**Model choice — a deliberate, documented departure from
`AI_BLUEPRINT.md` §10's "RECOMMENDED" (not `LOCKED`) XGBoost + SHAP
suggestion.** That suggestion was written against the Blueprint §8.4
future-production model, gated on 500+ resolved cases (§8.4's own
threshold) — nothing close to that volume exists in this repository today
(the seeded demo dataset has 7 terminal, diagnosed cases for `acc_demo`; see
`documentation/ai-memory/DECISIONS.md` for the exact count and this
decision's full reasoning). Fitting a gradient-boosted tree ensemble and
computing SHAP values on single-digit-to-low-double-digit rows would be
statistically meaningless and would add two heavyweight dependencies
(`xgboost`, `shap`) for a demo that cannot exercise either honestly. Phase
7's own governing task explicitly instructs: "Do NOT optimize for model
sophistication," "a simple scikit-learn baseline is acceptable if the
dependency is justified," and "choose the model based on the actual
target/feature structure after inspecting the repository."

**Chosen: `sklearn.linear_model.LogisticRegression`** over a
`DictVectorizer`-encoded feature dict (handles the mix of numeric and
open-vocabulary categorical fields — e.g. `root_cause_code` — without a
hand-rolled encoder, and treats an unseen category at prediction time as
"contributes nothing" rather than raising). Deterministic
(`random_state=0`; `lbfgs` itself needs no randomness to converge, but the
parameter is set explicitly rather than relying on a solver-specific
default). Its fitted coefficients are directly inspectable per-feature
signed weights — a natural, dependency-free stand-in for "explainability"
at this scale, and the same linear-model family the eventual XGBoost+SHAP
upgrade would be benchmarked against, so nothing here needs to be thrown
away when that future model is built.

**Degenerate-data handling.** `LogisticRegression.fit` raises when given
only one class. Rather than let a small, real, single-outcome-class
dataset crash training, `LogisticRegressionShadowModel` detects this case
and falls back to a constant predictor (the observed class's rate — `1.0`
or `0.0`), documented on the model instance and reflected honestly in
`torque.ai.shadow.training.ShadowTrainingReport.limitations`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from statistics import fmean

from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from torque.ai.exceptions import InsufficientTrainingDataError, ModelNotFittedError
from torque.ai.shadow.schemas import ShadowFeatureVector, ShadowTrainingExample

#: The Blueprint §8.4 numeric fields. Each gets a companion
#: `"<name>_missing"` indicator column (see `_row_dict`) so a missing value
#: is distinguishable from a genuine, meaningful zero.
_NUMERIC_FIELDS = (
    "diagnosis_confidence",
    "amount_at_risk",
    "days_since_failure",
    "promise_keeping_rate",
    "risk_score",
)

#: The Blueprint §8.4 categorical fields. `None` is mapped to an explicit
#: `"MISSING"` category rather than omitted, so "no mandate type recorded"
#: is itself a feature `DictVectorizer` can learn from, not silent absence.
_CATEGORICAL_FIELDS = ("leg_type", "root_cause_code", "mandate_type", "network_directive_tier")


def _numeric_value(features: ShadowFeatureVector, name: str) -> float | None:
    if name == "amount_at_risk":
        return float(features.amount_at_risk)
    value = getattr(features, name)
    return None if value is None else float(value)


def _training_means(examples: Sequence[ShadowTrainingExample]) -> dict[str, float]:
    """Per-numeric-field mean over only the non-missing training values —
    used to impute a missing value at both fit and predict time. A field
    that is missing for every training example (e.g. `risk_score`, which
    has no writer anywhere in the codebase today) imputes to `0.0`."""
    means: dict[str, float] = {}
    for name in _NUMERIC_FIELDS:
        present = [
            v
            for ex in examples
            if (v := _numeric_value(ex.features, name)) is not None
        ]
        means[name] = fmean(present) if present else 0.0
    return means


def _row_dict(features: ShadowFeatureVector, means: Mapping[str, float]) -> dict[str, float | str]:
    """One `DictVectorizer`-ready row: numeric fields pass through as floats
    (imputed-to-mean + a `_missing` indicator when absent), categorical
    fields pass through as strings (one-hot expanded by the vectorizer,
    `None` mapped to the explicit `"MISSING"` category)."""
    row: dict[str, float | str] = {}
    for name in _NUMERIC_FIELDS:
        value = _numeric_value(features, name)
        if value is None:
            row[name] = means[name]
            row[f"{name}_missing"] = 1.0
        else:
            row[name] = value
            row[f"{name}_missing"] = 0.0
    for name in _CATEGORICAL_FIELDS:
        value = getattr(features, name)
        row[name] = str(value) if value else "MISSING"
    return row


class ShadowModel(ABC):
    """The small, replaceable model interface every Phase 7 (and future
    Phase 8+) shadow model implements — deliberately mirrors
    `torque.ai.providers.base.LLMProvider`'s shape (an injected,
    swappable dependency identified by a stable id string)."""

    @abstractmethod
    def fit(self, examples: Sequence[ShadowTrainingExample]) -> None:
        """Fit the model on `examples`. Raises `InsufficientTrainingDataError`
        if `examples` is empty. Never partially fits — either this call
        succeeds and `is_fitted` becomes `True`, or it raises and the
        model's prior state (fitted or not) is unchanged."""

    @abstractmethod
    def predict_proba(self, features: ShadowFeatureVector) -> float:
        """The model's estimated probability, in `[0, 1]`, that the case
        described by `features` eventually recovers. Raises
        `ModelNotFittedError` if called before `fit`."""

    @abstractmethod
    def model_id(self) -> str:
        """A stable, human-readable identifier for this model
        implementation + version (never a training-run identity — two
        `LogisticRegressionShadowModel` instances fit on different data
        share the same `model_id`)."""

    @property
    @abstractmethod
    def is_fitted(self) -> bool: ...


class LogisticRegressionShadowModel(ShadowModel):
    """The Phase 7 baseline — see the module docstring for the full
    model-choice rationale."""

    _MODEL_ID = "sklearn-logistic-regression-v1"

    def __init__(self) -> None:
        self._vectorizer: DictVectorizer | None = None
        self._classifier: LogisticRegression | None = None
        self._means: dict[str, float] = {}
        #: Set instead of `_classifier` when training data contains only
        #: one outcome class — see the module docstring's "Degenerate-data
        #: handling" note.
        self._constant_probability: float | None = None
        self._n_training_examples: int = 0

    @property
    def is_fitted(self) -> bool:
        return self._classifier is not None or self._constant_probability is not None

    @property
    def n_training_examples(self) -> int:
        return self._n_training_examples

    def fit(self, examples: Sequence[ShadowTrainingExample]) -> None:
        if not examples:
            raise InsufficientTrainingDataError(
                "cannot fit a shadow model on zero labeled examples"
            )
        means = _training_means(examples)
        labels = [1 if ex.label else 0 for ex in examples]

        if len(set(labels)) < 2:
            # Only one outcome class present — a real, honest possibility on
            # a small dataset. Fall back to a constant predictor rather than
            # let sklearn raise.
            self._means = means
            self._vectorizer = None
            self._classifier = None
            self._constant_probability = float(labels[0])
            self._n_training_examples = len(examples)
            return

        rows = [_row_dict(ex.features, means) for ex in examples]
        vectorizer = DictVectorizer(sparse=False)
        design_matrix = vectorizer.fit_transform(rows)
        classifier = LogisticRegression(max_iter=1000, random_state=0)
        classifier.fit(design_matrix, labels)

        self._means = means
        self._vectorizer = vectorizer
        self._classifier = classifier
        self._constant_probability = None
        self._n_training_examples = len(examples)

    def predict_proba(self, features: ShadowFeatureVector) -> float:
        if not self.is_fitted:
            raise ModelNotFittedError("predict_proba called before fit")
        if self._constant_probability is not None:
            return self._constant_probability
        assert self._vectorizer is not None and self._classifier is not None
        row = _row_dict(features, self._means)
        design_row = self._vectorizer.transform([row])
        # LogisticRegression.classes_ is [0, 1] for a binary fit — column 1
        # is P(label == 1 == "recovered").
        return float(self._classifier.predict_proba(design_row)[0][1])

    def model_id(self) -> str:
        return self._MODEL_ID


__all__ = ["LogisticRegressionShadowModel", "ShadowModel"]
