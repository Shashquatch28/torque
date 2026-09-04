"""Phase 3 — the retrieval / precedent engine.

    current case
        v
    merchant_id + leg_type + root_cause_code   (primary, exact-match filter)
        v
    same-merchant, terminal/resolved historical cases
        v
    Postgres full-text search (secondary lexical signal — CaseEvent.reasoning
    + root_cause_label — ranks WITHIN the already-filtered candidate set)
        v
    recency (tiebreak / dominant ordering when the lexical signal is flat)
        v
    top-K
        v
    list[PrecedentCase]

`find_precedent` answers "has this merchant previously experienced a
comparable resolved case, and if so, what happened?" — informational only.
It never recommends an action, never scores an intervention, and never
influences any Torque decision. An empty list is a first-class, expected,
successful result — not an error, not `None`, not a fabricated placeholder.

**Retrieval strategy (v1, per documentation/ai-memory/AI_BLUEPRINT.md §8).**
Postgres-native full-text search (`to_tsvector`/`plainto_tsquery`/`ts_rank`)
over the ALREADY exact-metadata-filtered candidate set — never a substitute
for that filter, only a secondary ranking signal within it. No vector
database, no embedding model, no ANN index: the current corpus (dozens to
low hundreds of cases) does not justify infrastructure built for sub-linear
search over millions of rows. No new index/migration either — at this scale
a sequential scan over `revenue_leak_case` is the expected, acceptable plan
(verified via `EXPLAIN ANALYZE` against the seeded dataset; see
`documentation/ai-memory/MILESTONES.md`'s "AI Phase 3" section for the
recorded plan). See `documentation/ai-memory/DECISIONS.md` D-142.

**Terminal-state determination — a deliberate, documented duplication.**
`torque.ai`'s forbidden-import boundary (`tests/test_ai_boundary.py`, kept
"permanent" per this phase's own governing instructions) blocks the whole
`torque.state_machine` module — including its pure, non-mutating
`TERMINAL_STATUSES` / `is_terminal`. Rather than narrow that boundary test
(a live option, left for the maintainer — see D-142), this module mirrors
`is_terminal`'s exact logic locally, byte-for-byte, and that mirror is
cross-tested against the real function in
`tests/test_ai_retrieval.py::test_terminal_mirror_matches_state_machine_exactly`
(a test file, unlike `src/torque/ai/*`, is free to import the real thing for
comparison) — so any future drift between the two breaks the build loudly,
rather than silently.

**Import boundary.** This module imports `torque.db.scoped.TenantScope`,
`torque.models.{RevenueLeakCase,CaseEvent}`, `torque.enums`, and
`torque.ai.schemas` — the same allowed surface `torque.ai.evidence` already
uses. It does NOT import `torque.state_machine`, `torque.coordination`,
`torque.events`, `torque.agent_console`, `torque.execution`,
`torque.ingestion`, `torque.policy`, `torque.diagnosis`, `torque.scoring`,
`torque.reconciliation`, or `torque.promises` — enforced by
`tests/test_ai_boundary.py`.

**Read-only.** No `session.add`, `.delete`, or `.commit` anywhere in this
module — every function here only ever calls `session.scalars(select(...))`
or `session.execute(select(...))`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torque.ai.schemas import EvidenceReference, PrecedentCase, SourceType
from torque.db.scoped import TenantScope
from torque.enums import CaseEventType, CaseStatus, LegType
from torque.models import CaseEvent, RevenueLeakCase

#: Default and maximum number of precedents `find_precedent` returns. A
#: caller-supplied `top_k` outside `[1, MAX_TOP_K]` is rejected — retrieval
#: never returns an unbounded/unrestricted result set.
DEFAULT_TOP_K = 3
MAX_TOP_K = 10

#: Byte-for-byte mirror of `torque.state_machine.TERMINAL_STATUSES` — see
#: the module docstring's "Terminal-state determination" note.
_ALWAYS_TERMINAL: frozenset[CaseStatus] = frozenset(
    {
        CaseStatus.RECOVERED,
        CaseStatus.EXHAUSTED,
        CaseStatus.CANCELLED,
        CaseStatus.WRITTEN_OFF,
    }
)

#: The two resolution event types the blueprint names as authoritative for
#: an outcome summary (§20 of the Phase 3 task).
_RESOLUTION_EVENT_TYPES = (CaseEventType.PAYMENT_RECONCILED, CaseEventType.HUMAN_RESOLVED)


def _terminal_statuses_for_leg(leg_type: LegType) -> frozenset[CaseStatus]:
    """Mirrors `torque.state_machine.is_terminal` exactly: `PARTIALLY_RECOVERED`
    is terminal for every leg EXCEPT `B2B_RECEIVABLE` (a partial B2B payment
    keeps the case open for further dunning of the remainder)."""
    if LegType(leg_type) is LegType.B2B_RECEIVABLE:
        return _ALWAYS_TERMINAL
    return _ALWAYS_TERMINAL | {CaseStatus.PARTIALLY_RECOVERED}


def _reference_id(
    *,
    source_type: SourceType,
    source_id: str,
    case_id: str,
    event_seq_id: int | None,
    timestamp,
) -> str:
    """Computes a `reference_id` via the real `EvidenceReference` model
    (`torque.ai.schemas`) — the single source of truth for the id format
    established in Phase 1/2 — rather than hand-formatting a string here."""
    return EvidenceReference(
        source_type=source_type,
        source_id=source_id,
        case_id=case_id,
        event_seq_id=event_seq_id,
        timestamp=timestamp,
    ).reference_id


def _candidate_cases(
    session: Session, scope: TenantScope, case: RevenueLeakCase
) -> list[RevenueLeakCase]:
    """The primary, exact-match metadata filter: same merchant (via
    `scope`), same `leg_type`, same `root_cause_code`, terminal/resolved
    only, never the current case itself, never a superseded (merged-away)
    row — the same `superseded_by_case_id.is_(None)` convention every other
    live-case query in the codebase uses (e.g. `torque.scoring.score`,
    `torque.reporting.{metrics,incrementality}`)."""
    leg_type = LegType(case.leg_type)
    terminal = _terminal_statuses_for_leg(leg_type)
    stmt = scope.select(RevenueLeakCase).where(
        RevenueLeakCase.leg_type == leg_type,
        RevenueLeakCase.root_cause_code == case.root_cause_code,
        RevenueLeakCase.case_id != case.case_id,
        RevenueLeakCase.superseded_by_case_id.is_(None),
        RevenueLeakCase.status.in_([s.value for s in terminal]),
    )
    return list(session.scalars(stmt).all())


def _lexical_ranks(
    session: Session, query_text: str, case_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float]:
    """Postgres full-text search: `ts_rank` of each candidate case's
    `CaseEvent.reasoning` (+ its `root_cause_label`, joined from the case
    row) against `plainto_tsquery(query_text)`, aggregated as the MAX rank
    across that case's events. `NULL` reasoning is coalesced to an empty
    string — a candidate with no matching text is simply absent from the
    returned dict; callers must default a missing key to `0.0`, never treat
    absence as an error.

    Restricted to `case_ids` (the already metadata-filtered candidate set) —
    this is a secondary ranking signal WITHIN that set, never a substitute
    for it. Not scoped through `TenantScope` itself (`CaseEvent` carries no
    `merchant_id` — same posture `torque.ai.evidence` and
    `torque.reporting.metrics` document under INV-58) — safe because
    `case_ids` is already the output of a tenant-scoped query.
    """
    if not case_ids or not query_text:
        return {}
    tsquery = func.plainto_tsquery("english", query_text)
    document = func.to_tsvector(
        "english",
        func.concat(
            func.coalesce(CaseEvent.reasoning, ""),
            " ",
            func.coalesce(RevenueLeakCase.root_cause_label, ""),
        ),
    )
    stmt = (
        select(CaseEvent.case_id, func.max(func.ts_rank(document, tsquery)))
        .join(RevenueLeakCase, RevenueLeakCase.case_id == CaseEvent.case_id)
        .where(CaseEvent.case_id.in_(case_ids))
        .group_by(CaseEvent.case_id)
    )
    return {row[0]: float(row[1]) for row in session.execute(stmt).all()}


def _resolution_event(session: Session, case_id: uuid.UUID) -> CaseEvent | None:
    """The candidate's own most recent resolution event (`PAYMENT_RECONCILED`
    or `HUMAN_RESOLVED`) — the authoritative source for `outcome_summary`.
    `None` for a terminal case with neither (e.g. `EXHAUSTED` — the playbook
    ran out of attempts with no reconciled payment and no human
    resolution)."""
    stmt = (
        select(CaseEvent)
        .where(
            CaseEvent.case_id == case_id,
            CaseEvent.event_type.in_([t.value for t in _RESOLUTION_EVENT_TYPES]),
        )
        .order_by(CaseEvent.event_seq_id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def _outcome_summary(candidate: RevenueLeakCase, resolution_event: CaseEvent | None) -> str:
    """A short, deterministic summary — root cause, resolution, recovered
    amount — assembled only from case-level fields and the resolution
    event's own locked, schema-validated payload keys (`recovery_type` /
    `resolution`). Never quotes free-form `CaseEvent.reasoning` text: this
    stays a template over a small, fixed set of facts, not generated
    narrative — no LLM is involved anywhere in Phase 3."""
    root_cause = (
        candidate.root_cause_label or candidate.root_cause_code or "an unspecified root cause"
    )
    amount = candidate.recovered_amount
    amount_clause = f"₹{amount} recovered" if amount and amount > 0 else "no amount recovered"

    if resolution_event is not None:
        event_type = CaseEventType(resolution_event.event_type)
        payload = resolution_event.payload or {}
        if event_type is CaseEventType.PAYMENT_RECONCILED:
            recovery_type = payload.get("recovery_type", "unspecified")
            return f"{root_cause}; payment reconciled ({recovery_type}), {amount_clause}."
        resolution = payload.get("resolution", "unspecified")
        return f"{root_cause}; human-resolved as {resolution}, {amount_clause}."

    status_label = str(candidate.status).replace("_", " ").lower()
    return f"{root_cause}; case {status_label}, {amount_clause}."


def _evidence_id_for(candidate: RevenueLeakCase, resolution_event: CaseEvent | None) -> str:
    """The citation target for this precedent — the resolution event that
    grounds `outcome_summary` if one exists, otherwise the candidate case's
    own snapshot reference. Resolves through Phase 2's `resolve_citation`
    against THAT case's own `gather_case_evidence(...)` result — never
    against the current case's evidence set."""
    case_id = str(candidate.case_id)
    if resolution_event is not None:
        return _reference_id(
            source_type="case_event",
            source_id=str(resolution_event.event_seq_id),
            case_id=case_id,
            event_seq_id=resolution_event.event_seq_id,
            timestamp=resolution_event.timestamp,
        )
    return _reference_id(
        source_type="case",
        source_id=case_id,
        case_id=case_id,
        event_seq_id=None,
        timestamp=candidate.opened_at,
    )


def find_precedent(
    session: Session,
    merchant_id: str,
    case: RevenueLeakCase,
    *,
    top_k: int = DEFAULT_TOP_K,
) -> list[PrecedentCase]:
    """Find up to `top_k` comparable, resolved historical cases for `case`,
    scoped to `merchant_id`.

    Returns `[]` — never `None`, never an exception — when: `case` has no
    `root_cause_code` yet (insufficient retrieval keys; never silently
    broadened to "every merchant case"); no other case at this merchant
    shares the same `(leg_type, root_cause_code)`; or every same-metadata
    case is still in-flight (not yet terminal). A `[]` result is a
    successful, first-class outcome — the future narrative layer (Phase 4+,
    not built) turns it into an explicit "no comparable resolved case
    exists yet" message; that message is not implemented here.
    """
    if top_k < 1 or top_k > MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}, got {top_k}")
    if str(case.merchant_id) != merchant_id:
        raise ValueError(
            f"case {case.case_id} belongs to merchant {case.merchant_id!r}, "
            f"not {merchant_id!r}"
        )
    if not case.root_cause_code:
        return []

    scope = TenantScope(session, merchant_id)
    candidates = _candidate_cases(session, scope, case)
    if not candidates:
        return []

    query_text = case.root_cause_label or case.root_cause_code
    ranks = _lexical_ranks(session, query_text, [c.case_id for c in candidates])

    ordered = sorted(
        candidates,
        key=lambda c: (ranks.get(c.case_id, 0.0), c.opened_at),
        reverse=True,
    )
    top = ordered[:top_k]

    results: list[PrecedentCase] = []
    for candidate in top:
        resolution_event = _resolution_event(session, candidate.case_id)
        results.append(
            PrecedentCase(
                case_id=str(candidate.case_id),
                root_cause_code=candidate.root_cause_code,
                outcome_summary=_outcome_summary(candidate, resolution_event),
                recovered=bool(candidate.recovered_amount and candidate.recovered_amount > 0),
                evidence_id=_evidence_id_for(candidate, resolution_event),
            )
        )
    return results


__all__ = ["DEFAULT_TOP_K", "MAX_TOP_K", "find_precedent"]
