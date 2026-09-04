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
    must equal exactly (§10 of the Phase 4 task)."""
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


def _validate_citations(
    narrative: CaseNarrative,
    evidence: CaseEvidence,
    precedents: list[PrecedentCase],
) -> None:
    """The Phase 4 hard safety check (§11 of the task): every citation id
    the narrative uses must resolve against the evidence actually supplied
    to this generation call — never merely "look plausible."

    A current-case citation resolves through Phase 2's `resolve_citation`
    against `evidence` directly. A precedent citation is valid iff it
    exactly equals one of `precedents`' own `evidence_id` values — those
    were already constructed and proven resolvable by `find_precedent`
    itself (Phase 3, tested); re-deriving that proof here would only add
    redundant queries, not additional safety.

    Raises `NarrativeGenerationError` — never silently discards a bad
    citation, never repairs one, never invents a replacement — on: any
    used or flat-listed id that does not resolve, or a flat `citations`
    list that does not exactly equal the set of ids actually used by
    claim-bearing fields (missing or extra, either is a contract
    violation).
    """
    precedent_ids = {p.evidence_id for p in precedents}

    def _is_resolvable(citation_id: str) -> bool:
        return citation_id in precedent_ids or resolve_citation(evidence, citation_id) is not None

    used_ids = _collect_claim_citation_ids(narrative)
    flat_ids = {c.evidence_id for c in narrative.citations}

    unresolved = sorted(cid for cid in used_ids | flat_ids if not _is_resolvable(cid))
    if unresolved:
        raise NarrativeGenerationError(
            f"narrative cites unresolvable evidence id(s): {unresolved}"
        )

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
    cross-tenant case (from `gather_case_evidence`, before any provider call
    is even attempted) and `torque.ai.exceptions.NarrativeGenerationError`
    for any provider/generation failure (see the module docstring).
    """
    settings = get_ai_settings()
    max_tokens = settings.max_tokens if max_tokens is None else max_tokens
    timeout_s = settings.timeout_s if timeout_s is None else timeout_s

    case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
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
        raw_result = await provider.structured_generate(
            system=system,
            user=user,
            schema=CaseNarrative,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
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
