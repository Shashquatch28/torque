"""Phase 7 — score one case with an already-fitted `ShadowModel`.

    TenantScope.get(case)          (tenant-verified, same as
            v                       torque.ai.evidence/retrieval)
    extract_features()             (torque.ai.shadow.features)
            v
    model.predict_proba()          (torque.ai.shadow.model, injected —
            v                       never constructed/trained here)
    ShadowPrediction

Mirrors `torque.ai.narrative.explain_case`'s own shape: the model is
received by dependency injection (never imported/constructed by this
module), and the case is re-fetched through `TenantScope` for the same
never-a-cross-tenant-leak posture `torque.ai.evidence.gather_case_evidence`
already establishes — `EvidenceNotFoundError` for an unknown OR
wrong-tenant case, never distinguished.

Unlike `explain_case`, this function is synchronous — a `ShadowModel`'s
`predict_proba` is a pure, in-process computation (no network call, no
LLM), so there is no I/O-bound step here to justify `async`.

**No persistence anywhere in this module or this phase.** There is no
"the fitted model" this function reaches for on its own — a caller (e.g. a
future API route, if one is ever built, or a test/notebook) must have
already produced one via `torque.ai.shadow.training.train_and_evaluate_shadow_model`
or an equivalent `.fit(...)` call and pass it in. Model persistence across
requests is explicitly out of scope for Phase 7 — see
`documentation/ai-memory/AI_BLUEPRINT.md`'s Phase 7 section.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from torque.ai.exceptions import EvidenceNotFoundError
from torque.ai.shadow.features import extract_features
from torque.ai.shadow.model import ShadowModel
from torque.ai.shadow.schemas import FEATURE_SCHEMA_VERSION, ShadowPrediction
from torque.db.scoped import TenantScope
from torque.models import RevenueLeakCase


def score_case(
    session: Session,
    *,
    merchant_id: str,
    case_id: uuid.UUID | str,
    model: ShadowModel,
    n_training_cases: int,
) -> ShadowPrediction:
    """Score one case with `model` (already fitted — see the module
    docstring). Raises `EvidenceNotFoundError` for an unknown or
    cross-tenant case, OR a malformed `case_id` (Phase 8 hardening — never
    a raw `uuid.UUID(...)` `ValueError`), and
    `torque.ai.exceptions.FeatureExtractionError` (propagated unchanged
    from `extract_features`) for a case that has not been diagnosed yet.
    `n_training_cases` is the caller's responsibility to supply accurately
    (e.g. from the `ShadowTrainingReport` that produced `model`) — this
    function has no way to independently verify it without re-running
    training, which it deliberately never does on a hot scoring path.
    """
    try:
        case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise EvidenceNotFoundError(f"malformed case id {case_id!r}") from exc
    scope = TenantScope(session, merchant_id)
    case = scope.get(RevenueLeakCase, case_uuid)
    if case is None:
        raise EvidenceNotFoundError(
            f"no case {case_id!r} for merchant {merchant_id!r}"
        )

    features = extract_features(session, merchant_id=merchant_id, case=case)
    probability = model.predict_proba(features)

    return ShadowPrediction(
        case_id=str(case.case_id),
        merchant_id=merchant_id,
        model_id=model.model_id(),
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        generated_at=datetime.now(UTC),
        predicted_recovery_probability=probability,
        predicted_label=probability >= 0.5,
        n_training_cases=n_training_cases,
    )


__all__ = ["score_case"]
