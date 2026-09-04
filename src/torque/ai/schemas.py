"""Read-only AI evidence DTOs — Phase 1 (evidence) + Phase 2 (citations).

These are the ONLY objects `torque.ai.evidence` ever returns. No ORM/domain
object crosses this boundary: every field here is a plain, JSON-serializable,
already-redacted value copied out of an authoritative Torque row — never the
row itself, never a live session reference.

**Phase 2 addition.** `Citation` and the `EvidenceItem` type alias establish
the citation contract a future claim-generation phase (Phase 4+, not built
yet) will consume:

    CaseEvidence (the "evidence set" for one case)
            v
    EvidenceItem.reference.reference_id   (stable, Phase 1)
            v
    Citation(evidence_id=...)
            v
    torque.ai.citations.resolve_citation(evidence, evidence_id)
            v
    the exact EvidenceItem, or None if unresolvable

See `torque.ai.citations` for the (pure, no-database) resolution logic.

**Untrusted-text contract (§1.7).** `TimelineEntry.reasoning` and
`TimelineEntry.payload` carry free text / structured data written by
deterministic engine code today (`CaseEvent.reasoning`, `CaseEvent.payload`).
Nothing in this module or in `torque.ai.evidence` parses, evaluates, or acts
on their contents — they are opaque `str` / `dict` values, full stop. A
future phase that serializes these into an LLM prompt (Phase 3+, not built
yet) must treat them as DATA, never as instructions, and must not assume this
text is free of adversarial content merely because it currently only comes
from deterministic code (a case-event payload channel, once it also carries
merchant- or customer-authored text, degrades no differently).

**PII policy.** `Counterparty.name` / `.phone` / `.email` and
`Action.content_sent` are never read into any DTO below — see
`torque.ai.evidence`'s field-by-field allowlist. `CaseEvent.payload` is safe
to pass through verbatim because it is validated against its locked,
closed (`extra="forbid"`) per-`event_type` schema at write time
(`torque.events.payloads`) and none of those locked schemas carry a raw PII
field — see `documentation/ai-memory/AI_BLUEPRINT.md` §"Read-only evidence
architecture" for the field-by-field audit.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, computed_field

SourceType = Literal[
    "case", "case_event", "action", "promise", "counterparty_relationship"
]


class EvidenceReference(BaseModel):
    """A citation identifier — the traceable link from one piece of AI
    evidence back to the exact authoritative Torque row it was derived from.

    This is Phase 1's citation-architecture foundation (no citation-bearing
    prose exists yet — that is a future phase). `reference_id` is the stable,
    deterministic string any future citation object will point to; it is
    assigned exactly once, here, and never re-derived downstream.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: SourceType
    source_id: str
    case_id: str
    #: Set only for a `source_type="case_event"` reference — `CaseEvent`'s
    #: globally-ordered, autoincrement sequence id (INV-20).
    event_seq_id: int | None = None
    timestamp: datetime

    @computed_field  # type: ignore[misc]
    @property
    def reference_id(self) -> str:
        return f"{self.source_type}:{self.source_id}"


class TimelineEntry(BaseModel):
    """One `CaseEvent`, redacted and reformatted for AI consumption.

    Preserves authoritative ordering: entries are always returned by
    `torque.ai.evidence.gather_case_evidence` in `CaseEvent.event_seq_id`
    order (§1.3) — never re-sorted or re-inferred from `reasoning` text.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: EvidenceReference
    event_type: str
    actor: str
    timestamp: datetime
    #: `CaseEvent.reasoning` verbatim, or `None` if the event carries none.
    #: DATA, NOT INSTRUCTIONS — see the module docstring.
    reasoning: str | None
    #: `CaseEvent.payload` verbatim (already schema-validated at write time,
    #: see the module docstring's PII-policy note). DATA, NOT INSTRUCTIONS.
    payload: dict[str, Any]


class ActionEvidence(BaseModel):
    """One `Action`, redacted.

    `content_sent` is deliberately never exposed here — it is Torque's own
    PII-erasure-cascade target (`torque.models.action.Action.content_sent`
    docstring: "the erasure-cascade target").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: EvidenceReference
    action_type: str
    channel: str | None
    outcome: str
    block_reason: str | None
    executed_at: datetime | None
    #: Decimal serialized as a string (project convention — see
    #: `RecoveryScore.to_dict`/`.explain()`), or `None` if unpriced.
    cost: str | None


class PromiseEvidence(BaseModel):
    """One `PromiseToPay`, redacted (it carries no PII of its own — only an
    amount, a date, and a status)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: EvidenceReference
    status: str
    promised_amount: str
    promised_date: date


class CounterpartyRelationshipEvidence(BaseModel):
    """`Merchant_Counterparty` aggregate fields only — never `Counterparty`
    itself. `torque.ai.evidence` does not query `Counterparty` at all; there
    is no code path here that could read `name` / `phone` / `email`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: EvidenceReference
    promise_keeping_rate: float | None
    risk_score: float | None


class CaseSnapshot(BaseModel):
    """The case's own current-state fields — not its history (see
    `CaseEvidence.timeline` for that).

    Deliberately excludes `RevenueLeakCase.context` (leg-typed JSON that may
    carry leg-specific identifiers not needed for AI reasoning) and any
    direct `Counterparty` reference.

    **Phase 2:** carries its own `reference` (`source_type="case"` — a
    `SourceType` value `EvidenceReference` already reserved in Phase 1 but
    that nothing constructed until now), making the snapshot's own facts
    (status, root cause, recovery score, ...) citable the same way a
    `CaseEvent`/`Action`/`PromiseToPay` already is. This was a genuine gap in
    Phase 1 — not a defect in anything Phase 1 already cited, simply an
    absence — closed here because Phase 2's whole purpose is making evidence
    referenceable. See `documentation/ai-memory/DECISIONS.md` D-140.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: EvidenceReference
    case_id: str
    leg_type: str
    status: str
    #: Decimal serialized as a string (project convention).
    amount_at_risk: str
    root_cause_code: str | None
    root_cause_label: str | None
    diagnosis_confidence: float | None
    network_directive_tier: str | None
    opened_at: datetime
    closed_at: datetime | None
    #: Post-outcome field, included here for narrative use (explaining an
    #: already-resolved case). A future shadow-ML feature-extraction path
    #: (not built in Phase 0+1) MUST read a separate, narrower field set that
    #: excludes this — see AI_BLUEPRINT.md's leakage-boundary note.
    recovery_type: str | None
    recovered_amount: str | None
    recovery_score: str | None
    recovery_score_breakdown: dict[str, Any] | None
    escalation_resolution: str | None


#: Every citable evidence-item type actually produced by
#: `torque.ai.evidence.gather_case_evidence` — no source type is invented
#: beyond what Phase 1 already models. A plain `typing` union, not a new
#: runtime class: `torque.ai.citations.resolve_citation` returns one of
#: these five existing types, never a wrapper around them.
EvidenceItem = (
    CaseSnapshot
    | TimelineEntry
    | ActionEvidence
    | PromiseEvidence
    | CounterpartyRelationshipEvidence
)


class Citation(BaseModel):
    """A reference to exactly one piece of evidence, by its stable
    `evidence_id` (the `EvidenceReference.reference_id` of the item it
    points to).

    This is the whole contract, deliberately minimal (Phase 2): nothing
    generates or validates citation-bearing prose yet — that is a future
    phase (Phase 4+). A `Citation` says only "this evidence_id, and nothing
    else." No excerpt, no claim text, no confidence score — those belong to
    whatever future object actually carries generated prose, not to the
    citation primitive itself.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str


class PrecedentCase(BaseModel):
    """Phase 3 — one comparable, resolved historical case surfaced by
    `torque.ai.retrieval.find_precedent` for the SAME merchant.

    Deliberately small, mirroring `Citation`'s own minimalism: enough to say
    *which* prior case, *what* its root cause and outcome were, and *how* to
    trace that outcome back to authoritative evidence — nothing that reads
    as a recommendation. Retrieval is informational only; it never answers
    "what should Torque do," only "has this happened before, and what
    happened."

    `evidence_id` resolves through the existing Phase 2 `resolve_citation`
    primitive — but against *that precedent case's own*
    `gather_case_evidence(...)` result, not the current case's. No new
    citation mechanism, no new id scheme: this is the same
    `EvidenceReference.reference_id` format Phase 1/2 already established.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    root_cause_code: str
    #: A short, deterministic, template-derived summary (root cause,
    #: resolution, recovered amount) — never free-form/LLM-generated prose.
    outcome_summary: str
    #: Whether any money came back on this case (`recovered_amount > 0`) —
    #: independent of who gets attribution credit (Module 9's
    #: Torque-attributed vs. self-recovered distinction is a separate,
    #: orthogonal concern this field does not encode).
    recovered: bool
    evidence_id: str


class CaseEvidence(BaseModel):
    """The complete Phase-1 evidence set for one case.

    This is the single return type of
    `torque.ai.evidence.gather_case_evidence` — no caller downstream of it
    ever sees an ORM row, a live `Session`, or a `Counterparty`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    merchant_id: str
    snapshot: CaseSnapshot
    #: `CaseEvent`-derived, `event_seq_id`-ordered. Empty list — not a
    #: fabricated placeholder entry — for a case with no history yet (§1.8).
    timeline: list[TimelineEntry]
    actions: list[ActionEvidence]
    promises: list[PromiseEvidence]
    #: `None` only if no `Merchant_Counterparty` relationship row exists yet
    #: (should not normally happen — every case has one from ingestion — but
    #: represented explicitly rather than assumed, per §1.8).
    counterparty_relationship: CounterpartyRelationshipEvidence | None
    #: Explicit, human-readable statements of what is missing — never a
    #: fabricated fact standing in for absent data (§1.8). Empty when nothing
    #: is missing.
    evidence_gaps: list[str]
    gathered_at: datetime


# --- Phase 4: generated-narrative contract ----------------------------------


class NarrativeClaim(BaseModel):
    """One claim-bearing sentence in a generated `CaseNarrative` — the LLM's
    unit of assertion, always paired with the citation ids that support it.

    **Deliberately NOT named `TimelineEntry`, despite the Phase 4 task's own
    wording suggesting that name.** `TimelineEntry` (above) already means
    something structurally different and load-bearing since Phase 1: one
    raw, uninterpreted `CaseEvent` evidence item inside `CaseEvidence.
    timeline`, with fields `reference` / `event_type` / `actor` /
    `timestamp` / `reasoning` / `payload` — nothing like `claim` +
    `citation_ids`. Reusing that name for this unrelated shape would either
    silently redefine an existing, tested, Phase 1-3 class (forbidden — "do
    not redesign existing interfaces unnecessarily") or collide two
    incompatible meanings under one name. `NarrativeClaim` is the same
    `claim: str` / `citation_ids: list[str]` contract the task describes,
    under a name that does not collide. See `documentation/ai-memory/
    DECISIONS.md` for the recorded reasoning.

    `citation_ids` may be empty ONLY when the claim itself states that
    evidence is missing (e.g. "no diagnosis has been recorded yet"); a
    substantive factual claim about the case must cite something. Every id
    used here must resolve against the evidence actually supplied to the
    generation call — enforced by `torque.ai.narrative` after generation,
    not merely requested of the model (§11 of the Phase 4 task).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str
    citation_ids: list[str]


class PrecedentSection(BaseModel):
    """The narrative's precedent block — always present, even when empty.

    `found=False` with an empty `cases` list and the fixed note below is the
    correct, honest representation of "no comparable resolved case exists
    yet" (Phase 3's `find_precedent() == []`) — never a fabricated case,
    never `None` standing in for the whole section.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    found: bool
    cases: list[PrecedentCase]
    note: str


#: The fixed, non-LLM-authored note used whenever `find_precedent` returned
#: `[]` — the orchestration layer supplies this text; the model is
#: instructed never to invent its own precedent-not-found phrasing (§19 of
#: the Phase 4 task).
NO_PRECEDENT_NOTE = "No comparable resolved case exists yet for this root cause."


class CaseNarrative(BaseModel):
    """Phase 4 — the structured, citation-grounded output of
    `torque.ai.narrative.explain_case`.

    The LLM's job is synthesis, explanation, and organization of evidence
    already gathered by the deterministic core (Phase 1) and precedent
    already retrieved by Phase 3 — never diagnosis, scoring, policy,
    playbook selection, action execution, or state transition (none of
    which this schema even has a field for).

    **`case_id` / `generated_at` / `provider_id` / `prompt_version` are
    never trusted from the provider.** `explain_case` always overwrites
    these four fields with orchestrator-known-correct values after
    validation (`model_copy(update={...})`) — a hallucinating or malicious
    provider cannot misattribute a narrative to the wrong case, claim a
    fake generation time, or claim to be a different provider/prompt
    version than the one that actually ran. The provider still must supply
    *some* schema-valid value for each (Pydantic requires it), but nothing
    downstream ever reads what it supplied.

    `recommended_human_attention` is plain text only — a suggestion for
    what a human reviewer might want to look at, grounded in the evidence.
    It is never parsed as a command and nothing in Torque executes it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    generated_at: datetime
    summary: str
    current_state: NarrativeClaim
    root_cause_explanation: NarrativeClaim
    timeline: list[NarrativeClaim]
    actions_taken: list[NarrativeClaim]
    guardrail_explanation: list[NarrativeClaim]
    precedent: PrecedentSection
    recommended_human_attention: str | None
    uncertainty: str
    evidence_gaps: list[str]
    #: The de-duplicated union of every `citation_ids` value used across
    #: `current_state` / `root_cause_explanation` / `timeline` /
    #: `actions_taken` / `guardrail_explanation`, plus every `precedent.
    #: cases[*].evidence_id` — enforced exactly, not just "a superset," by
    #: `torque.ai.narrative`'s post-generation validation.
    citations: list[Citation]
    provider_id: str
    prompt_version: str


__all__ = [
    "ActionEvidence",
    "CaseEvidence",
    "CaseNarrative",
    "CaseSnapshot",
    "Citation",
    "CounterpartyRelationshipEvidence",
    "EvidenceItem",
    "EvidenceReference",
    "NarrativeClaim",
    "NO_PRECEDENT_NOTE",
    "PrecedentCase",
    "PrecedentSection",
    "PromiseEvidence",
    "SourceType",
    "TimelineEntry",
]
