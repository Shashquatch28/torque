"""Phase 1 — the read-only AI evidence interface.

    Torque authoritative state
            v
    AI read-only evidence adapter   (this module)
            v
    structured AI evidence          (torque.ai.schemas.CaseEvidence)
            v
    citation resolution              (torque.ai.citations — Phase 2)
            v
    future retrieval / LLM layer    (not built yet)

`gather_case_evidence` is the ONLY function in this module, and the only
public read entry point of the `torque.ai` package as of Phase 0 + Phase 1.
It:

* reads exclusively through `torque.db.scoped.TenantScope` — the same,
  unmodified tenant-isolation facade every other Torque read path uses
  (§1.5, Blueprint §2.1, INV-01);
* returns only `torque.ai.schemas` DTOs — never an ORM row (§1.2);
* excludes every field on the PII / sensitive-data exclusion list (§1.6):
  `Counterparty.name` / `.phone` / `.email` (this module never queries
  `Counterparty` at all) and `Action.content_sent`;
* represents missing evidence as an explicit empty list / `None` value plus
  an `evidence_gaps` entry — never a fabricated placeholder (§1.8);
* treats `CaseEvent.reasoning` and `.payload` as inert data end-to-end — see
  `torque.ai.schemas.TimelineEntry`'s docstring (§1.7).

This module does not implement retrieval, embeddings, an LLM call, or a
shadow ML model — none of that exists yet (see `AI_BLUEPRINT.md`'s phase
roadmap). It also does not write anything: no `session.add`, no
`session.flush` beyond what `TenantScope`'s read path already does, no
`session.commit` anywhere in this file.

**Import boundary.** This module imports nothing from `torque.state_machine`,
`torque.coordination`, `torque.events`, `torque.agent_console`,
`torque.execution`, `torque.ingestion`, `torque.policy`, `torque.diagnosis`,
`torque.scoring`, `torque.reconciliation`, or `torque.promises` — enforced by
`tests/test_ai_boundary.py`, not merely by this docstring.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.ai.exceptions import EvidenceNotFoundError
from torque.ai.schemas import (
    ActionEvidence,
    CaseEvidence,
    CaseSnapshot,
    CounterpartyRelationshipEvidence,
    EvidenceReference,
    PromiseEvidence,
    SourceType,
    TimelineEntry,
)
from torque.db.scoped import TenantScope
from torque.models import (
    Action,
    CaseEvent,
    MerchantCounterparty,
    PromiseToPay,
    RevenueLeakCase,
)


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _reference(
    *,
    source_type: SourceType,
    source_id: str,
    case_id: str,
    event_seq_id: int | None,
    timestamp: datetime,
) -> EvidenceReference:
    return EvidenceReference(
        source_type=source_type,
        source_id=source_id,
        case_id=case_id,
        event_seq_id=event_seq_id,
        timestamp=timestamp,
    )


def _snapshot(case: RevenueLeakCase) -> CaseSnapshot:
    return CaseSnapshot(
        reference=_reference(
            source_type="case",
            source_id=str(case.case_id),
            case_id=str(case.case_id),
            event_seq_id=None,
            timestamp=case.opened_at,
        ),
        case_id=str(case.case_id),
        leg_type=str(case.leg_type),
        status=str(case.status),
        amount_at_risk=_money(case.amount_at_risk) or "0",
        root_cause_code=case.root_cause_code,
        root_cause_label=case.root_cause_label,
        diagnosis_confidence=case.diagnosis_confidence,
        network_directive_tier=(
            str(case.network_directive_tier) if case.network_directive_tier else None
        ),
        opened_at=case.opened_at,
        closed_at=case.closed_at,
        recovery_type=(str(case.recovery_type) if case.recovery_type else None),
        recovered_amount=_money(case.recovered_amount),
        recovery_score=_money(case.recovery_score),
        recovery_score_breakdown=case.recovery_score_breakdown,
        escalation_resolution=case.escalation_resolution,
    )


def _timeline(session: Session, case: RevenueLeakCase) -> list[TimelineEntry]:
    """`CaseEvent`-derived, `event_seq_id`-ordered timeline (§1.3).

    `CaseEvent` carries no `merchant_id` column — it is deliberately not
    `TenantScoped` (ownership is transitive through `case_id`; the same
    posture `torque.reporting.metrics` documents for this exact table under
    INV-58: "`case_event` (no `merchant_id`) is filtered by a join to
    `revenue_leak_case.merchant_id`"). `case` above was already fetched
    through `TenantScope`, so filtering `CaseEvent` by `case.case_id` here
    cannot cross a tenant boundary — the case's ownership was already
    verified before this function is ever called.
    """
    rows = session.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .order_by(CaseEvent.event_seq_id)
    ).all()
    return [
        TimelineEntry(
            reference=_reference(
                source_type="case_event",
                source_id=str(row.event_seq_id),
                case_id=str(case.case_id),
                event_seq_id=row.event_seq_id,
                timestamp=row.timestamp,
            ),
            event_type=str(row.event_type),
            actor=str(row.actor),
            timestamp=row.timestamp,
            reasoning=row.reasoning,
            payload=row.payload or {},
        )
        for row in rows
    ]


def _actions(
    session: Session, scope: TenantScope, case: RevenueLeakCase
) -> list[ActionEvidence]:
    stmt = (
        scope.select(Action)
        .where(Action.primary_case_id == case.case_id)
        .order_by(Action.created_at)
    )
    rows = session.scalars(stmt).all()
    return [
        ActionEvidence(
            reference=_reference(
                source_type="action",
                source_id=str(row.action_id),
                case_id=str(case.case_id),
                event_seq_id=None,
                timestamp=row.executed_at or row.created_at,
            ),
            action_type=str(row.action_type),
            channel=row.channel,
            outcome=str(row.outcome),
            block_reason=(str(row.block_reason) if row.block_reason else None),
            executed_at=row.executed_at,
            cost=_money(row.cost),
        )
        for row in rows
    ]


def _promises(
    session: Session, scope: TenantScope, case: RevenueLeakCase
) -> list[PromiseEvidence]:
    stmt = (
        scope.select(PromiseToPay)
        .where(PromiseToPay.case_id == case.case_id)
        .order_by(PromiseToPay.created_at)
    )
    rows = session.scalars(stmt).all()
    return [
        PromiseEvidence(
            reference=_reference(
                source_type="promise",
                source_id=str(row.promise_id),
                case_id=str(case.case_id),
                event_seq_id=None,
                timestamp=row.created_at,
            ),
            status=str(row.status),
            promised_amount=_money(row.promised_amount) or "0",
            promised_date=row.promised_date,
        )
        for row in rows
    ]


def _counterparty_relationship(
    session: Session, scope: TenantScope, case: RevenueLeakCase
) -> CounterpartyRelationshipEvidence | None:
    """`Merchant_Counterparty` aggregate fields only. Never queries
    `Counterparty` (§1.6) — there is no field of raw PII this function could
    even accidentally read."""
    stmt = scope.select(MerchantCounterparty).where(
        MerchantCounterparty.counterparty_id == case.counterparty_id
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return CounterpartyRelationshipEvidence(
        reference=_reference(
            source_type="counterparty_relationship",
            source_id=str(row.id),
            case_id=str(case.case_id),
            event_seq_id=None,
            timestamp=row.created_at,
        ),
        promise_keeping_rate=row.promise_keeping_rate,
        risk_score=row.risk_score,
    )


def _evidence_gaps(
    snapshot: CaseSnapshot,
    timeline: list[TimelineEntry],
    actions: list[ActionEvidence],
) -> list[str]:
    """Explicit, human-readable statements of what is missing (§1.8) — never
    a fabricated fact standing in for absent data."""
    gaps: list[str] = []
    if snapshot.root_cause_code is None:
        gaps.append("No diagnosis has been recorded for this case yet.")
    if snapshot.recovery_score is None:
        gaps.append("No recovery score has been computed for this case yet.")
    if not timeline:
        gaps.append("No case history events are recorded yet.")
    if not actions:
        gaps.append("No actions have been taken on this case yet.")
    return gaps


def gather_case_evidence(
    session: Session, *, merchant_id: str, case_id: uuid.UUID | str
) -> CaseEvidence:
    """The Phase-1 evidence interface.

    Raises `EvidenceNotFoundError` for an unknown case OR a case belonging to
    a different merchant — the two are never distinguished (never a
    cross-tenant leak, the same posture `torque.agent_console.resolve` /
    `CaseNotFoundError` uses, §1.5).

    Read-only: no write, flush-of-a-pending-change, or commit occurs in this
    function or anything it calls.
    """
    scope = TenantScope(session, merchant_id)
    case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
    case = scope.get(RevenueLeakCase, case_uuid)
    if case is None:
        raise EvidenceNotFoundError(
            f"no case {case_uuid} found for merchant {merchant_id!r}"
        )

    snapshot = _snapshot(case)
    timeline = _timeline(session, case)
    actions = _actions(session, scope, case)
    promises = _promises(session, scope, case)
    counterparty_relationship = _counterparty_relationship(session, scope, case)
    gaps = _evidence_gaps(snapshot, timeline, actions)

    return CaseEvidence(
        case_id=str(case.case_id),
        merchant_id=merchant_id,
        snapshot=snapshot,
        timeline=timeline,
        actions=actions,
        promises=promises,
        counterparty_relationship=counterparty_relationship,
        evidence_gaps=gaps,
        gathered_at=datetime.now(UTC),
    )


__all__ = ["gather_case_evidence"]
