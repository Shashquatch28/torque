"""Phase 7 — the shadow-ML feature extractor. DB-touching, read-only,
tenant-scoped.

Deliberately a *separate, narrower* read path from
`torque.ai.evidence.gather_case_evidence` — never imports it, never shares
code with it. `gather_case_evidence` deliberately returns post-outcome
fields (`recovery_type`, `recovered_amount`, `recovery_score`, ...) because
it exists to explain an already-resolved case to a human reviewer; feeding
any of that into a model that predicts the outcome would be pure label
leakage. See `documentation/ai-memory/AI_BLUEPRINT.md` §11's leakage
boundary and `torque.ai.schemas.CaseSnapshot`'s own docstring warning.

**Temporal correctness — the `as_of` cutoff.** Every feature is computed
"as of" the case's own `DIAGNOSIS_COMPLETED` event timestamp — the exact
scheme the Blueprint §8.4 feature set requires, this is the earliest point
at which a real prediction could ever be made, since `root_cause_code` and
`diagnosis_confidence` do not exist before then. Concretely:

- `root_cause_code` / `diagnosis_confidence` are read directly off the
  current `RevenueLeakCase` row. This is safe without event-time
  reconstruction because diagnosis happens **at most once** per case
  (INV-35) and is never revised afterward — the current value already
  *is* the value as of diagnosis time.
- `network_directive_tier` is **not** read off the current row, because
  unlike diagnosis it can change after diagnosis completes (the tier only
  ratchets toward more restrictive, INV-05, and a new
  `NETWORK_DIRECTIVE_RECEIVED` event can arrive at any point in the case's
  active life). Using the case's *final* tier for a closed case would risk
  leaking a directive that arrived only because the case was already
  failing. Instead this module replays `NETWORK_DIRECTIVE_RECEIVED` events
  up to (and including) the cutoff and takes the most-restrictive tier seen
  by then, via `torque.models.guards.tier_rank` — the same ranking the
  deterministic engine itself uses to decide monotonicity.
- `amount_at_risk` is read off the current row for every leg **except**
  `B2B_RECEIVABLE`, whose `amount_at_risk` Module 7 actively decrements as
  invoices are paid off (INV-55) — for a closed, fully-recovered B2B case
  the live value would simply be `0`, a direct outcome leak. For B2B this
  module instead sums `B2BInvoice.original_amount` (set once at ingestion,
  never mutated by reconciliation).
- `promise_keeping_rate` / `risk_score` are read directly off
  `MerchantCounterparty` — as of this writing neither field has any writer
  anywhere in the codebase that updates it *during* a case's life (see
  `documentation/ai-memory/AI_BLUEPRINT.md`'s Phase 7 completion notes for
  the exact audit); they are effectively static per-counterparty inputs
  today, so no cutoff-aware reconstruction is needed or possible.
- `mandate_type` is read from the case's own typed `context` — set once at
  case creation for `SUBSCRIPTION_FAILURE` cases and never mutated.

**Import boundary.** Same allowed surface as `torque.ai.evidence`/
`torque.ai.retrieval`: `torque.db.scoped.TenantScope`, `torque.models`,
`torque.enums`, `torque.ai.shadow.schemas`, plus
`torque.models.guards.tier_rank` (a pure ranking function — `torque.models`
is not on the forbidden-prefix list; only `torque.state_machine`,
`torque.coordination`, `torque.events`, `torque.agent_console`,
`torque.execution`, `torque.ingestion`, `torque.policy`, `torque.diagnosis`,
`torque.scoring`, `torque.reconciliation`, `torque.promises`, and
`torque.api` are — see `tests/test_ai_boundary.py`).

**Read-only.** No `session.add`, `.delete`, or `.commit` anywhere in this
module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.ai.exceptions import FeatureExtractionError
from torque.ai.shadow.labels import is_training_eligible, recovered_label
from torque.ai.shadow.schemas import (
    FEATURE_SCHEMA_VERSION,
    ShadowFeatureVector,
    ShadowTrainingExample,
)
from torque.db.scoped import TenantScope
from torque.enums import CaseEventType, LegType, MacTier
from torque.models import B2BInvoice, CaseEvent, MerchantCounterparty, RevenueLeakCase
from torque.models.guards import tier_rank


def _aware(dt: datetime) -> datetime:
    """Torque's `DateTime(timezone=True)` columns are always aware in
    practice; this is a defensive normalization only (mirrors the same
    `_aware` convention `torque.scoring.score` documents for the identical
    reason), not evidence that naive datetimes are expected."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _diagnosis_completed_at(session: Session, case: RevenueLeakCase) -> datetime | None:
    """The timestamp of `case`'s own (at-most-one, INV-35) `DIAGNOSIS_COMPLETED`
    event — the prediction-time cutoff every other feature is computed
    against. `None` if no such event exists (should not happen when
    `case.diagnosis_confidence is not None`, given diagnosis writes both
    atomically per INV-36, but never assumed — callers check explicitly).

    Not tenant-scoped itself (`CaseEvent` carries no `merchant_id`) — safe
    because `case` is only ever passed in after the caller already resolved
    it through `TenantScope`, the same INV-58 posture
    `torque.ai.evidence`/`torque.ai.retrieval` already document.
    """
    stmt = (
        select(CaseEvent.timestamp)
        .where(
            CaseEvent.case_id == case.case_id,
            CaseEvent.event_type == CaseEventType.DIAGNOSIS_COMPLETED,
        )
        .order_by(CaseEvent.event_seq_id.asc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def _tier_as_of(session: Session, case: RevenueLeakCase, cutoff: datetime) -> MacTier | None:
    """The most-restrictive `MacTier` named by a `NETWORK_DIRECTIVE_RECEIVED`
    event for `case` with `timestamp <= cutoff` — see the module docstring's
    "Temporal correctness" note for why this is reconstructed from events
    rather than read off the case's current (possibly later-tightened)
    column value."""
    stmt = select(CaseEvent.payload).where(
        CaseEvent.case_id == case.case_id,
        CaseEvent.event_type == CaseEventType.NETWORK_DIRECTIVE_RECEIVED,
        CaseEvent.timestamp <= cutoff,
    )
    best: MacTier | None = None
    for payload in session.scalars(stmt).all():
        tier = MacTier(payload["tier"])
        if tier_rank(tier) > tier_rank(best):
            best = tier
    return best


def _amount_at_risk(session: Session, merchant_id: str, case: RevenueLeakCase) -> Decimal:
    """`Σ B2BInvoice.original_amount` for a B2B case (immutable, pre-outcome);
    `case.amount_at_risk` unchanged for every other leg (never mutated
    post-creation for non-B2B legs — Module 7 only ever writes
    `recovery_type`/`recovered_amount` there, per INV-06)."""
    if LegType(case.leg_type) is not LegType.B2B_RECEIVABLE:
        return case.amount_at_risk
    scope = TenantScope(session, merchant_id)
    stmt = scope.select(B2BInvoice).where(B2BInvoice.case_id == case.case_id)
    invoices = session.scalars(stmt).all()
    total = Decimal("0")
    for invoice in invoices:
        total += invoice.original_amount
    return total


def _mandate_type(case: RevenueLeakCase) -> str | None:
    """Only `SUBSCRIPTION_FAILURE` cases carry a `mandate_type` at all — set
    once, in the typed `context`, at case creation (never mutated)."""
    if LegType(case.leg_type) is not LegType.SUBSCRIPTION_FAILURE:
        return None
    context = case.context or {}
    raw = context.get("mandate_type")
    return str(raw) if raw else None


def _counterparty_relationship(
    session: Session, merchant_id: str, case: RevenueLeakCase
) -> MerchantCounterparty | None:
    scope = TenantScope(session, merchant_id)
    stmt = scope.select(MerchantCounterparty).where(
        MerchantCounterparty.counterparty_id == case.counterparty_id
    )
    return session.scalars(stmt).first()


def extract_features(
    session: Session, *, merchant_id: str, case: RevenueLeakCase
) -> ShadowFeatureVector:
    """Build the exact Blueprint §8.4 feature vector for `case`, as of its
    own diagnosis-completion cutoff.

    Raises `FeatureExtractionError` if `case` has not been diagnosed yet
    (`root_cause_code`/`diagnosis_confidence` are `None`) or — the one
    genuinely-unexpected case, given INV-35/36 — a diagnosis is recorded on
    the row but no `DIAGNOSIS_COMPLETED` event can be found. Never
    fabricates a placeholder feature vector for either case.
    """
    if str(case.merchant_id) != merchant_id:
        raise ValueError(
            f"case {case.case_id} belongs to merchant {case.merchant_id!r}, not {merchant_id!r}"
        )
    if case.diagnosis_confidence is None or not case.root_cause_code:
        raise FeatureExtractionError(
            f"case {case.case_id} has not been diagnosed yet — shadow features "
            "require root_cause_code and diagnosis_confidence"
        )
    as_of = _diagnosis_completed_at(session, case)
    if as_of is None:
        raise FeatureExtractionError(
            f"case {case.case_id} has a recorded diagnosis but no DIAGNOSIS_COMPLETED "
            "event was found to anchor a prediction-time cutoff"
        )
    as_of = _aware(as_of)
    opened_at = _aware(case.opened_at)
    days_since_failure = max((as_of - opened_at).total_seconds() / 86400.0, 0.0)

    amount_at_risk = _amount_at_risk(session, merchant_id, case)
    mandate_type = _mandate_type(case)
    tier = _tier_as_of(session, case, as_of)
    counterparty = _counterparty_relationship(session, merchant_id, case)

    return ShadowFeatureVector(
        case_id=str(case.case_id),
        merchant_id=merchant_id,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        as_of=as_of,
        leg_type=str(LegType(case.leg_type).value),
        root_cause_code=case.root_cause_code,
        diagnosis_confidence=case.diagnosis_confidence,
        amount_at_risk=str(amount_at_risk),
        days_since_failure=days_since_failure,
        promise_keeping_rate=counterparty.promise_keeping_rate if counterparty else None,
        risk_score=counterparty.risk_score if counterparty else None,
        mandate_type=mandate_type,
        network_directive_tier=tier.value if tier else None,
    )


def build_shadow_dataset(
    session: Session, *, merchant_id: str
) -> list[ShadowTrainingExample]:
    """The full labeled training population for one merchant: every
    terminal, diagnosed case, each paired with its
    `torque.ai.shadow.labels.recovered_label`.

    Tenant-scoped (`TenantScope`) — never reads another merchant's cases.
    A terminal case that was never diagnosed (e.g. a pre-diagnosis
    self-recovery, §7.1.4) is silently excluded from the labeled
    population — it is not an error, it simply has no Blueprint §8.4
    features to compute (D-058: ingestion never classifies a decline;
    diagnosis is Module 3's job, and it never ran for that case).
    """
    scope = TenantScope(session, merchant_id)
    stmt = scope.select(RevenueLeakCase)
    examples: list[ShadowTrainingExample] = []
    for case in session.scalars(stmt).all():
        if not is_training_eligible(case.status, case.leg_type):
            continue
        if case.diagnosis_confidence is None or not case.root_cause_code:
            continue
        try:
            features = extract_features(session, merchant_id=merchant_id, case=case)
        except FeatureExtractionError:
            continue
        examples.append(
            ShadowTrainingExample(features=features, label=recovered_label(case.status))
        )
    return examples


__all__ = ["build_shadow_dataset", "extract_features"]
