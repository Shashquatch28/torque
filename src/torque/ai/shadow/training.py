"""Phase 7 — training orchestration.

    build_shadow_dataset()        (torque.ai.shadow.features, DB-touching)
            v
    temporal_train_test_split()   (pure)
            v
    ShadowModel.fit(train)        (torque.ai.shadow.model, pure)
            v
    compute_classification_metrics(test)   (torque.ai.shadow.evaluation, pure)
    + majority_class_baseline_proba(train) (same)
            v
    ShadowTrainingReport

**Temporal split, not random.** Examples are sorted by their own
`ShadowFeatureVector.as_of` (the case's diagnosis-completion timestamp) and
the split point falls at a fixed fraction from the end — the earliest-
diagnosed cases train, the most-recently-diagnosed cases test. This mirrors
how the model would actually be used (train on the past, evaluate on what
came after) and avoids the optimistic bias a random shuffle would introduce
by letting the model "see the future" relative to some test examples during
training. No randomness anywhere in this module — the same `(dataset,
test_fraction)` input always produces the same split, the same fit, and the
same report.

**Honesty about sample size — not a formality.** The seeded demo dataset
(`torque.demo.seed.seed_demo`) produces exactly 7 terminal, diagnosed cases
for its one demo merchant — nowhere near enough for a statistically
meaningful held-out evaluation, let alone the Blueprint §8.4 future
model's own 500-case production gate. `insufficient_data` is a first-class,
always-checked field on every `ShadowTrainingReport` this module produces,
and `MIN_CASES_FOR_MEANINGFUL_EVALUATION` documents exactly why 30 (a
common statistical rule-of-thumb floor, not a Torque-specific number) was
chosen as the line below which a report says so explicitly, in addition to
the always-present `test_metrics`/`baseline_metrics` numbers themselves
(never suppressed — a reader can see exactly how few test examples backed
them).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from torque.ai.shadow.evaluation import (
    compute_classification_metrics,
    majority_class_baseline_proba,
)
from torque.ai.shadow.features import build_shadow_dataset
from torque.ai.shadow.model import LogisticRegressionShadowModel, ShadowModel
from torque.ai.shadow.schemas import (
    FEATURE_SCHEMA_VERSION,
    SHADOW_DISCLAIMER,
    ShadowTrainingExample,
    ShadowTrainingReport,
)

#: Module 9b's own intent-to-treat definition, restated here for the
#: report's own `target_definition` field (see `torque.ai.shadow.labels`
#: for the enforced implementation).
TARGET_DEFINITION = (
    "recovered = status in {RECOVERED, CANCELLED} as of the case's terminal "
    "status — the customer's at-risk money came back, by any means. "
    "Identical to torque.reporting.incrementality's own intent-to-treat "
    "definition (see documentation/ai-memory/DECISIONS.md)."
)

SPLIT_METHOD = "temporal (sorted by diagnosis-completion cutoff; no shuffling)"

DEFAULT_TEST_FRACTION = 0.2

#: Below this many *total* labeled cases, there is not even enough data for
#: a train/test split to mean anything — the model is fit on everything
#: available and no held-out evaluation is attempted at all.
MIN_CASES_FOR_SPLIT = 4

#: Below this many total labeled cases, a split IS attempted (if
#: `>= MIN_CASES_FOR_SPLIT`) but the report is still marked
#: `insufficient_data=True` — a common statistical rule-of-thumb floor for
#: "enough to say anything at all," not a number specific to this codebase.
MIN_CASES_FOR_MEANINGFUL_EVALUATION = 30


def temporal_train_test_split(
    examples: list[ShadowTrainingExample], *, test_fraction: float = DEFAULT_TEST_FRACTION
) -> tuple[list[ShadowTrainingExample], list[ShadowTrainingExample]]:
    """Sort `examples` by `features.as_of` ascending, then split so the
    earliest `1 - test_fraction` become the train set and the most recent
    `test_fraction` become the test set. Always leaves at least 1 example in
    train and, when `len(examples) >= 2`, at least 1 in test. Deterministic —
    no shuffling, no randomness.
    """
    if not 0.0 < test_fraction < 1.0:
        raise ValueError(f"test_fraction must be in (0, 1), got {test_fraction}")
    ordered = sorted(examples, key=lambda ex: (ex.features.as_of, ex.features.case_id))
    n = len(ordered)
    n_test = max(1, round(n * test_fraction)) if n >= 2 else 0
    n_test = min(n_test, n - 1) if n >= 2 else 0
    split_at = n - n_test
    return ordered[:split_at], ordered[split_at:]


def _class_distribution(examples: list[ShadowTrainingExample]) -> dict[str, int]:
    recovered = sum(1 for ex in examples if ex.label)
    return {"recovered": recovered, "not_recovered": len(examples) - recovered}


def train_and_evaluate_shadow_model(
    session: Session,
    *,
    merchant_id: str,
    model_factory: Callable[[], ShadowModel] = LogisticRegressionShadowModel,
    test_fraction: float = DEFAULT_TEST_FRACTION,
) -> ShadowTrainingReport:
    """Build the labeled dataset for `merchant_id`, split it temporally, fit
    `model_factory()` on the train split, and evaluate it (plus a
    majority-class baseline) on the test split.

    Always returns a `ShadowTrainingReport` — never raises for "not enough
    data," which is a first-class, expected, honestly-reported outcome
    (`insufficient_data=True` + a `limitations` entry), not a
    training failure. The one thing this function does not attempt is
    fitting on zero examples at all (`n_total_cases == 0`): the resulting
    report still carries every metadata field, with `test_metrics` /
    `baseline_metrics` both `None`.
    """
    dataset = build_shadow_dataset(session, merchant_id=merchant_id)
    n_total = len(dataset)
    class_distribution = _class_distribution(dataset)
    generated_at = datetime.now(UTC)
    model_id = model_factory().model_id()

    if n_total == 0:
        return ShadowTrainingReport(
            merchant_id=merchant_id,
            target_definition=TARGET_DEFINITION,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            model_id=model_id,
            generated_at=generated_at,
            n_total_cases=0,
            n_train=0,
            n_test=0,
            class_distribution=class_distribution,
            split_method=SPLIT_METHOD,
            test_metrics=None,
            baseline_metrics=None,
            insufficient_data=True,
            limitations=[
                "No terminal, diagnosed cases exist for this merchant yet — "
                "there is nothing to train or evaluate on."
            ],
            disclaimer=SHADOW_DISCLAIMER,
        )

    limitations: list[str] = []
    if n_total < MIN_CASES_FOR_MEANINGFUL_EVALUATION:
        limitations.append(
            f"Only {n_total} total labeled case(s) available for merchant "
            f"{merchant_id!r} — far below the {MIN_CASES_FOR_MEANINGFUL_EVALUATION}-case "
            "rule-of-thumb floor for a statistically meaningful evaluation. Every "
            "metric below is illustrative of the pipeline working end-to-end, not "
            "evidence of real predictive skill."
        )
    if class_distribution["recovered"] == 0 or class_distribution["not_recovered"] == 0:
        limitations.append(
            "The labeled dataset contains only one outcome class "
            f"({class_distribution!r}) — any model fit on it reduces to a constant "
            "predictor; no classifier can be meaningfully evaluated."
        )

    if n_total < MIN_CASES_FOR_SPLIT:
        model = model_factory()
        model.fit(dataset)
        limitations.append(
            f"Only {n_total} labeled case(s) — too few to hold any of them out for "
            "testing. The model is fit on all available data; no held-out evaluation "
            "was attempted (test_metrics/baseline_metrics are both None)."
        )
        return ShadowTrainingReport(
            merchant_id=merchant_id,
            target_definition=TARGET_DEFINITION,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            model_id=model_id,
            generated_at=generated_at,
            n_total_cases=n_total,
            n_train=n_total,
            n_test=0,
            class_distribution=class_distribution,
            split_method=SPLIT_METHOD,
            test_metrics=None,
            baseline_metrics=None,
            insufficient_data=True,
            limitations=limitations,
            disclaimer=SHADOW_DISCLAIMER,
        )

    train, test = temporal_train_test_split(dataset, test_fraction=test_fraction)
    model = model_factory()
    model.fit(train)

    y_true = [ex.label for ex in test]
    y_proba = [model.predict_proba(ex.features) for ex in test]
    test_metrics = compute_classification_metrics(y_true, y_proba)

    train_labels = [ex.label for ex in train]
    baseline_proba = majority_class_baseline_proba(train_labels, n=len(test))
    baseline_metrics = compute_classification_metrics(y_true, baseline_proba)

    if len(set(train_labels)) < 2:
        limitations.append(
            "The training split contains only one outcome class; the fitted model "
            "reduces to a constant-probability predictor (see torque.ai.shadow.model)."
        )

    return ShadowTrainingReport(
        merchant_id=merchant_id,
        target_definition=TARGET_DEFINITION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        model_id=model_id,
        generated_at=generated_at,
        n_total_cases=n_total,
        n_train=len(train),
        n_test=len(test),
        class_distribution=class_distribution,
        split_method=SPLIT_METHOD,
        test_metrics=test_metrics,
        baseline_metrics=baseline_metrics,
        insufficient_data=n_total < MIN_CASES_FOR_MEANINGFUL_EVALUATION,
        limitations=limitations,
        disclaimer=SHADOW_DISCLAIMER,
    )


__all__ = [
    "DEFAULT_TEST_FRACTION",
    "MIN_CASES_FOR_MEANINGFUL_EVALUATION",
    "MIN_CASES_FOR_SPLIT",
    "SPLIT_METHOD",
    "TARGET_DEFINITION",
    "temporal_train_test_split",
    "train_and_evaluate_shadow_model",
]
