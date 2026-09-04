"""Phase 2 — the citation resolution primitive.

    CaseEvidence (torque.ai.evidence's "evidence set" for one case)
            v
    stable evidence_id      (EvidenceReference.reference_id, Phase 1)
            v
    Citation                (torque.ai.schemas.Citation)
            v
    resolve_citation()      (this module)
            v
    exact EvidenceItem      (CaseSnapshot | TimelineEntry | ActionEvidence |
                              PromiseEvidence | CounterpartyRelationshipEvidence)
            v
    authoritative Torque record (traceable via EvidenceReference's
                                  source_type / source_id / case_id /
                                  event_seq_id — see torque.ai.evidence)

`resolve_citation` is pure: given an already-gathered `CaseEvidence` (the
Phase 1 evidence set for one case) and an `evidence_id` string, it returns
the matching evidence item or `None`. It performs NO database query, NO
`Session`, NO I/O of any kind — it is a plain lookup over Python objects
already sitting in memory. This is deliberate: a future faithfulness/
evaluation layer (not built yet) needs to validate every citation a
generated narrative produces, and that validation must be deterministic,
cheap, and independently testable without touching Postgres.

A citation that does not resolve — an unknown id, a fabricated id, a
malformed/empty id, or an id that belongs to a *different* case's evidence
set entirely — returns `None`. This module never raises for a bad id. A
future evaluation layer treats `None` as "unsupported claim," not as a
crash — see `documentation/ai-memory/AI_BLUEPRINT.md` for how that layer is
expected to consume this contract once it exists.

**Import boundary.** This module imports nothing beyond `torque.ai.schemas`
— no `sqlalchemy`, no `Session`, no `torque.db`, no `torque.models`. It
cannot query the database because it has no way to reach one; enforced by
`tests/test_ai_boundary.py`, not merely by this docstring.

**Not a lookup service.** There is no global registry, no cross-case index,
and no persistence anywhere in this module. `resolve_citation` only ever
searches the one `CaseEvidence` object it was handed — an id from case A's
evidence set is structurally incapable of resolving against case B's
(§8 of the Phase 2 task; see `tests/test_ai_citations.py::
test_wrong_case_evidence_id_does_not_resolve` /
`test_wrong_tenant_evidence_id_does_not_resolve`).
"""

from __future__ import annotations

from torque.ai.schemas import (
    CaseEvidence,
    Citation,
    EvidenceItem,
)


def all_evidence_items(evidence: CaseEvidence) -> list[EvidenceItem]:
    """Every citable item in one case's evidence set, as a flat list — the
    case snapshot itself, then its timeline, actions, promises, and (if
    present) counterparty relationship.

    Order is deterministic (snapshot, then timeline, then actions, then
    promises, then counterparty relationship) but carries no semantic
    meaning beyond that determinism — lookup is always by `evidence_id`,
    never by position (§4 of the Phase 2 task: "Do not use array position as
    the identifier").
    """
    items: list[EvidenceItem] = [evidence.snapshot]
    items.extend(evidence.timeline)
    items.extend(evidence.actions)
    items.extend(evidence.promises)
    if evidence.counterparty_relationship is not None:
        items.append(evidence.counterparty_relationship)
    return items


def resolve_citation(evidence: CaseEvidence, evidence_id: str) -> EvidenceItem | None:
    """Resolve one `evidence_id` against an already-gathered `CaseEvidence`.

    Returns the exact evidence item whose `reference.reference_id` equals
    `evidence_id`, or `None` if nothing in this evidence set matches —
    covering an unknown id, a fabricated id, a malformed/empty id, and an id
    that is well-formed but belongs to a different case's (or a different
    tenant's) evidence set. Never raises for any of those; `None` is the
    only failure signal, by design.
    """
    if not evidence_id:
        return None
    for item in all_evidence_items(evidence):
        if item.reference.reference_id == evidence_id:
            return item
    return None


def citation_for(item: EvidenceItem) -> Citation:
    """The `Citation` that points back to `item` — the inverse of
    `resolve_citation`. A small convenience so a future claim-generation
    phase never has to hand-construct a `Citation` from a raw string."""
    return Citation(evidence_id=item.reference.reference_id)


__all__ = ["all_evidence_items", "citation_for", "resolve_citation"]
