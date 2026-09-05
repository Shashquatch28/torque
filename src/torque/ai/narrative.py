"""Phase 4 — the narrative orchestration layer: the first real AI-generation
capability.

    gather_case_evidence()          (Phase 1, torque.ai.evidence)
            v
    find_precedent()                (Phase 3, torque.ai.retrieval)
            v
    build_narrative_prompt()        (this package, torque.ai.prompts)
            v
    provider.structured_generate()  (injected LLMProvider, Phase 4)
            v
    citation validation             (Phase 2's resolve_citation, this module)
            v
    CaseNarrative                   (stamped with orchestrator-trusted
                                      case_id / generated_at / provider_id /
                                      prompt_version)

`explain_case` is the single public entry point. No arrow in the pipeline
above ever points back into `torque.state_machine`, `torque.execution`,
`torque.coordination`, `torque.ingestion`, `torque.policy`,
`torque.diagnosis`, `torque.scoring`, `torque.reconciliation`, or
`torque.promises` — enforced by `tests/test_ai_boundary.py`, exactly as for
every other module in this package.

**The LLM never becomes a source of truth.** `explain_case` never trusts
the provider's own `case_id` / `generated_at` / `provider_id` /
`prompt_version` — those four fields are always overwritten with
orchestrator-known-correct values (`CaseNarrative.model_copy(update=...)`)
after validation succeeds, so a hallucinating or malicious provider cannot
misattribute a narrative to the wrong case. And the provider's CONTENT
(every claim, every citation) is validated against the exact evidence this
call supplied *before* any of it is trusted — see `_validate_citations`.

**On any failure — provider exception, schema-invalid response, a
non-`BaseModel` return, or an unresolvable citation — `explain_case` raises
`torque.ai.exceptions.NarrativeGenerationError` and returns nothing.** It
never returns a partial, repaired, or best-guess `CaseNarrative`; it never
silently discards or rewrites a fabricated citation into a valid one. The
original provider exception (if any) is chained via `from exc` for local
debugging only, never re-exposed verbatim to the caller. The deterministic
evidence (`CaseEvidence`, gathered first and separately) is entirely
unaffected by a generation failure — nothing about its own success depends
on generation succeeding afterward, and this whole module never writes
anything to the database in the first place.

**Stateless.** No `CaseNarrative` is ever persisted anywhere. Every call
regenerates from scratch, from the live evidence at call time. See
`documentation/ai-memory/DECISIONS.md`.

**`TORQUE_AI_ENABLED` is not checked here.** Gating whether this capability
is *exposed* to a user is an API-layer concern (Phase 6, not built yet);
`explain_case` itself stays fully callable and testable regardless of the
flag, exactly like every other function in this package — see
`torque.ai.config`'s docstring.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from torque.ai.citations import resolve_citation
from torque.ai.config import get_ai_settings
from torque.ai.evidence import gather_case_evidence
from torque.ai.exceptions import EvidenceNotFoundError, NarrativeGenerationError
from torque.ai.prompts import PROMPT_VERSION, build_narrative_prompt
from torque.ai.providers.base import LLMProvider
from torque.ai.retrieval import find_precedent
from torque.ai.schemas import CaseEvidence, CaseNarrative, PrecedentCase
from torque.db.scoped import TenantScope
from torque.models import RevenueLeakCase


def _collect_claim_citation_ids(narrative: CaseNarrative) -> set[str]:
    """Every citation id used by a claim-bearing field, plus every
    precedent case's own `evidence_id` — the set the flat `citations` list
    must equal exactly (§10 of the Phase 4 task).

    Retained as its own function (rather than inlined/removed) even though
    `_validate_citations` (Phase 8 hardening) no longer calls it directly —
    `tests/test_ai_evaluation.py::
    test_citation_collection_mirrors_narrative_validation_exactly` imports
    this exact symbol and cross-checks it against `torque.ai.evaluation`'s
    own independent mirror of the same "which ids are used" computation.
    Its return value (the *union* of claim ids and precedent ids) is
    unaffected by the Phase 8 fix, which only changed *which id-space*
    each half of that union must resolve against, not what counts as
    "used." `used_ids` in `_validate_citations` below is now computed
    inline as the equivalent union of `_claim_bearing_citation_ids(...)`
    and the precedent ids, so this function and that computation stay
    provably in sync by construction, not by two independent hand-copies.
    """
    ids: set[str] = set()
    ids.update(narrative.current_state.citation_ids)
    ids.update(narrative.root_cause_explanation.citation_ids)
    for entry in (
        *narrative.timeline,
        *narrative.actions_taken,
        *narrative.guardrail_explanation,
    ):
        ids.update(entry.citation_ids)
    ids.update(precedent_case.evidence_id for precedent_case in narrative.precedent.cases)
    return ids


def _claim_bearing_citation_ids(narrative: CaseNarrative) -> set[str]:
    """Every citation id used by a claim-bearing field
    (`current_state`/`root_cause_explanation`/`timeline`/`actions_taken`/
    `guardrail_explanation`) — excludes `precedent.cases[*].evidence_id`,
    which is a structurally different kind of citation (see
    `_validate_citations`'s "no masquerading" note)."""
    ids: set[str] = set()
    ids.update(narrative.current_state.citation_ids)
    ids.update(narrative.root_cause_explanation.citation_ids)
    for entry in (
        *narrative.timeline,
        *narrative.actions_taken,
        *narrative.guardrail_explanation,
    ):
        ids.update(entry.citation_ids)
    return ids


def _validate_citations(
    narrative: CaseNarrative,
    evidence: CaseEvidence,
    precedents: list[PrecedentCase],
) -> None:
    """The Phase 4 hard safety check (§11 of the task): every citation id
    the narrative uses must resolve against the evidence actually supplied
    to this generation call — never merely "look plausible."

    A current-case (claim-bearing-field) citation resolves through Phase
    2's `resolve_citation` against `evidence` directly — **and only
    against `evidence`**. A precedent citation (`precedent.cases[*].
    evidence_id`) is valid iff it exactly equals one of `precedents`' own
    `evidence_id` values — those were already constructed and proven
    resolvable by `find_precedent` itself (Phase 3, tested); re-deriving
    that proof here would only add redundant queries, not additional
    safety.

    **No masquerading, either direction (Phase 8 hardening).** A claim-
    bearing field describes the CURRENT case — a precedent's `evidence_id`
    must never satisfy it, even though that id is "resolvable" in a loose
    sense (against a different case's evidence set). Symmetrically, a
    precedent citation must never be satisfied by resolving against the
    current case's own evidence — a precedent slot describes a *different*,
    already-resolved case, and accepting a current-case id there would let
    the narrative fabricate a "precedent" that is actually just the current
    case restated. Each citation's context (which field it appears in)
    determines which one id-space it is checked against; there is no
    "resolves against either" fallback for any field.

    Raises `NarrativeGenerationError` — never silently discards a bad
    citation, never repairs one, never invents a replacement — on: any
    claim-bearing id that does not resolve against `evidence`, any
    precedent id that is not exactly one of `precedents`' own
    `evidence_id` values, or a flat `citations` list that does not exactly
    equal the union of both (missing or extra, either is a contract
    violation).
    """
    precedent_ids = {p.evidence_id for p in precedents}
    claim_ids = _claim_bearing_citation_ids(narrative)
    narrative_precedent_ids = {p.evidence_id for p in narrative.precedent.cases}

    unresolved_claims = sorted(
        cid for cid in claim_ids if resolve_citation(evidence, cid) is None
    )
    unresolved_precedents = sorted(
        cid for cid in narrative_precedent_ids if cid not in precedent_ids
    )
    if unresolved_claims or unresolved_precedents:
        raise NarrativeGenerationError(
            "narrative cites unresolvable evidence id(s): "
            f"claims={unresolved_claims}, precedent={unresolved_precedents}"
        )

    used_ids = claim_ids | narrative_precedent_ids
    flat_ids = {c.evidence_id for c in narrative.citations}
    if flat_ids != used_ids:
        missing = sorted(used_ids - flat_ids)
        extra = sorted(flat_ids - used_ids)
        raise NarrativeGenerationError(
            "narrative's flat citation list does not exactly match the citations "
            f"used by claim-bearing fields (missing={missing}, extra={extra})"
        )


async def explain_case(
    session: Session,
    *,
    merchant_id: str,
    case_id: uuid.UUID | str,
    provider: LLMProvider,
    max_tokens: int | None = None,
    timeout_s: float | None = None,
) -> CaseNarrative:
    """Generate a citation-grounded `CaseNarrative` for one case.

    Raises `torque.ai.exceptions.EvidenceNotFoundError` for an unknown or
    cross-tenant case, OR a malformed `case_id` (Phase 8 hardening — a
    malformed id is treated identically to "not found," never a raw
    `ValueError` escaping from `uuid.UUID(...)`), before any provider call
    is even attempted; and `torque.ai.exceptions.NarrativeGenerationError`
    for any provider/generation failure, including a provider that exceeds
    `timeout_s` (Phase 8 hardening — enforced by this function itself via
    `asyncio.wait_for`, not merely requested of the provider; see the
    module docstring).
    """
    settings = get_ai_settings()
    max_tokens = settings.max_tokens if max_tokens is None else max_tokens
    timeout_s = settings.timeout_s if timeout_s is None else timeout_s

    try:
        case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise EvidenceNotFoundError(f"malformed case id {case_id!r}") from exc
    evidence = gather_case_evidence(session, merchant_id=merchant_id, case_id=case_uuid)

    # A second, cheap PK lookup to bridge to Phase 3's find_precedent(),
    # which takes the ORM row — its own established signature, unchanged.
    # gather_case_evidence above already proved this case exists under this
    # exact merchant scope via the identical TenantScope.get() mechanism.
    case_row = TenantScope(session, merchant_id).get(RevenueLeakCase, case_uuid)
    if case_row is None:  # pragma: no cover - gather_case_evidence already proved existence
        raise EvidenceNotFoundError(f"no case {case_uuid} found for merchant {merchant_id!r}")

    precedents = find_precedent(session, merchant_id, case_row)

    system, user = build_narrative_prompt(evidence, precedents)

    try:
        # Phase 8 hardening: `timeout_s` is passed to the provider (which is
        # expected to respect it, per `LLMProvider`'s own docstring), AND
        # enforced here, independently, via `asyncio.wait_for`. A provider
        # that fails to honor its own timeout parameter (a bug, or a future
        # real network provider under unusual load) can therefore never hang
        # this call indefinitely — the orchestrator itself is the backstop,
        # not merely a hopeful caller of a cooperative provider.
        raw_result = await asyncio.wait_for(
            provider.structured_generate(
                system=system,
                user=user,
                schema=CaseNarrative,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
            ),
            timeout=timeout_s,
        )
    except Exception as exc:
        raise NarrativeGenerationError(
            f"provider {provider.provider_id()!r} failed to generate a narrative "
            f"for case {case_uuid}"
        ) from exc

    if not isinstance(raw_result, CaseNarrative):
        raise NarrativeGenerationError(
            f"provider {provider.provider_id()!r} returned "
            f"{type(raw_result).__name__}, not a CaseNarrative"
        )

    _validate_citations(raw_result, evidence, precedents)

    return raw_result.model_copy(
        update={
            "case_id": str(case_uuid),
            "generated_at": datetime.now(UTC),
            "provider_id": provider.provider_id(),
            "prompt_version": PROMPT_VERSION,
        }
    )


__all__ = ["explain_case"]
