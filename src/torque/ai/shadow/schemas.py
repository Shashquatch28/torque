"""Phase 7 — Shadow ML DTOs. Every object below is `extra="forbid"` +
`frozen=True`, the same convention every `torque.ai.schemas` DTO already
uses — nothing here is an ORM row or a live reference.

Kept in their own module (`torque.ai.shadow.schemas`, not appended to the
flat `torque.ai.schemas`) because Phase 7 is its own documented package
boundary (`AI_BLUEPRINT.md` §6 lists `shadow/` as a subpackage, not a set
of additions to the existing files) — this mirrors the same "give a
genuinely separate concern its own module" discipline
`torque.ai.providers` already established for Phase 4.

**Non-authoritative labeling is structural, not a naming convention.**
`ShadowPrediction` and `ShadowTrainingReport` both carry non-optional
`disclaimer` and (for `ShadowPrediction`) `n_training_cases` fields — per
`documentation/ai-memory/AI_BLUEPRINT.md` §10's explicit requirement, a
caller cannot construct or render one of these without the caveat
physically attached to it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

#: Bumped whenever the feature *shape* (which fields exist, what they mean,
#: how they are computed) changes in a way that would make an old
#: `ShadowFeatureVector`/a model fit on it incomparable with a new one.
FEATURE_SCHEMA_VERSION = "shadow-features-v1"

#: A fixed, non-optional caveat stamped onto every `ShadowPrediction` and
#: `ShadowTrainingReport` this package ever produces. Never LLM-authored,
#: never omitted, never rendered as anything resembling an authoritative
#: Torque score or recommendation.
SHADOW_DISCLAIMER = (
    "SHADOW / EXPERIMENTAL — NOT USED FOR DECISIONS. This prediction is "
    "produced by an observational, non-authoritative model that reads "
    "Torque's historical case data. It is never consulted by, and never "
    "influences, Torque's diagnosis, recovery scoring, playbook selection, "
    "guardrails, or any state transition. Torque's deterministic engine "
    "remains the sole authority for every case."
)


class ShadowFeatureVector(BaseModel):
    """The exact Blueprint §8.4 feature set for one case, computed as of a
    single, explicit `as_of` cutoff — never a later, outcome-adjacent
    timestamp. See `torque.ai.shadow.features` for how each field is
    derived and why `as_of` is fixed at the case's `DIAGNOSIS_COMPLETED`
    event (the earliest point at which a real prediction could actually be
    made, since `root_cause_code`/`diagnosis_confidence` do not exist
    before then).

    Every field is a case-level, pre-outcome fact. None of
    `RevenueLeakCase.recovery_type`, `.recovered_amount`,
    `.recovery_score`, `.recovery_score_breakdown`, `.escalation_resolution`,
    or `.closed_at` — the exact fields `torque.ai.schemas.CaseSnapshot`
    documents as post-outcome — appear anywhere in this model. This is a
    disjoint, narrower field set from `torque.ai.evidence.gather_case_evidence`
    on purpose (`AI_BLUEPRINT.md` §11's leakage boundary).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    merchant_id: str
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    #: The prediction-time cutoff every field below was computed as of —
    #: metadata for train/test splitting, never itself fed to a model.
    as_of: datetime

    leg_type: str
    root_cause_code: str | None
    diagnosis_confidence: float | None
    #: `Decimal`-as-`str`, matching the project-wide money convention
    #: (`torque.ai.schemas`' own `_money` helper). For `B2B_RECEIVABLE` this
    #: is `Σ B2BInvoice.original_amount` (immutable, pre-outcome), never the
    #: live `RevenueLeakCase.amount_at_risk`, which Module 7 decrements as
    #: invoices are paid (INV-55) — using the live value for a closed B2B
    #: case would leak the outcome directly.
    amount_at_risk: str
    days_since_failure: float
    promise_keeping_rate: float | None
    risk_score: float | None
    #: Only ever non-`None` for `SUBSCRIPTION_FAILURE` cases (the only leg
    #: whose typed context carries a `mandate_type` at all).
    mandate_type: str | None
    #: The most-restrictive `MacTier` value received on or before `as_of` —
    #: reconstructed from `NETWORK_DIRECTIVE_RECEIVED` events up to the
    #: cutoff, not read off the case's current (possibly later-tightened)
    #: column value, since the tier can ratchet tighter after diagnosis but
    #: before closure (INV-05).
    network_directive_tier: str | None


class ShadowTrainingExample(BaseModel):
    """One labeled row for training: a feature vector plus the ground-truth
    binary outcome (`torque.ai.shadow.labels.recovered_label`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    features: ShadowFeatureVector
    label: bool


class ShadowPrediction(BaseModel):
    """A single shadow-model prediction for one case. Non-authoritative by
    construction — see `SHADOW_DISCLAIMER` and the module docstring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    merchant_id: str
    model_id: str
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    generated_at: datetime
    predicted_recovery_probability: float = Field(ge=0.0, le=1.0)
    predicted_label: bool
    #: How many labeled cases the model that produced this prediction was
    #: actually trained on — always present so a caller cannot render a
    #: probability without also seeing how little (or much) data backs it.
    n_training_cases: int = Field(ge=0)
    disclaimer: str = SHADOW_DISCLAIMER


class ShadowClassificationMetrics(BaseModel):
    """Deterministic classification metrics over one evaluation set (a test
    split or a baseline comparison run over that same split). Any metric
    that is undefined for the given sample (e.g. ROC-AUC when only one
    class is present) is `None`, never a fabricated/default number."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_examples: int = Field(ge=0)
    accuracy: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    roc_auc: float | None = None
    #: Fraction of `n_examples` whose true label is `True` (recovered) —
    #: reported unconditionally so a reader can judge class imbalance
    #: without cross-referencing `ShadowTrainingReport.class_distribution`.
    positive_rate: float = Field(ge=0.0, le=1.0)


class ShadowTrainingReport(BaseModel):
    """The full account of one `train_and_evaluate_shadow_model(...)` run:
    what was trained on, how it was split, how it performed, and — always —
    an honest statement of whether there was enough data to mean anything.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    merchant_id: str
    target_definition: str
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    model_id: str
    generated_at: datetime

    n_total_cases: int = Field(ge=0)
    n_train: int = Field(ge=0)
    n_test: int = Field(ge=0)
    #: `{"recovered": <count>, "not_recovered": <count>}` over the full
    #: (train + test) labeled population.
    class_distribution: dict[str, int]
    split_method: str

    #: `None` only when there was no held-out test split at all (too few
    #: total cases — see `insufficient_data`/`limitations`).
    test_metrics: ShadowClassificationMetrics | None
    #: A majority-class predictor fit on the same train split and scored on
    #: the same test split, for direct baseline comparison. `None` under the
    #: same condition as `test_metrics`.
    baseline_metrics: ShadowClassificationMetrics | None

    #: `True` whenever the dataset is too small to support a statistically
    #: meaningful conclusion (see `torque.ai.shadow.training` for the exact
    #: threshold and reasoning) — set honestly, never suppressed to make a
    #: report look more confident than the data supports.
    insufficient_data: bool
    limitations: list[str]
    disclaimer: str = SHADOW_DISCLAIMER


__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "SHADOW_DISCLAIMER",
    "ShadowClassificationMetrics",
    "ShadowFeatureVector",
    "ShadowPrediction",
    "ShadowTrainingExample",
    "ShadowTrainingReport",
]
