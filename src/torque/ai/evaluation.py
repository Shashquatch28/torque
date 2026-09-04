"""Phase 5 — the citation / faithfulness evaluation harness.

Turns "the model appears grounded" into "groundedness and retrieval quality
are measured by deterministic, reproducible metrics." This module
EVALUATES the output Phase 4 already produced — it is not another
generation layer, and it does not generate anything itself.

    CaseNarrative + CaseEvidence + list[PrecedentCase]  (exactly what Phase
                                                          4 supplied to the
                                                          generation call)
            v
    evaluate_narrative()
            v
    EvaluationReport

**Absolute Data-Source Rule (§3 of the Phase 5 task).** `evaluate_narrative`
operates ONLY on the `CaseEvidence` and `list[PrecedentCase]` objects the
caller passes in — the exact ones supplied to the generation call being
evaluated. It never re-queries the database to ask "does this citation
resolve *now*." Re-querying would let the evidence context drift out from
under the narrative between generation and evaluation (a row could change,
a new event could land) and silently change what "supported" means —
exactly the evaluation leakage this rule exists to prevent. `evaluate_narrative`
is a pure function: no `Session` parameter, no import capable of reaching a
database, no I/O of any kind.

**`torque.ai.evaluate_retrieval_precision` is a deliberate exception, kept
structurally separate.** Measuring Phase 3 retrieval quality genuinely
requires calling `find_precedent` again (there is no other way to ask "what
would retrieval return for this case"), which requires a `Session`. This
function is read-only itself (it calls the same read-only `find_precedent`
Phase 3 already ships) but is never invoked by, or needed by,
`evaluate_narrative` — the two are independent entry points, and a caller
who only wants narrative metrics never touches a database at all.

**Deterministic v1 methodology — a documented, honest limitation, not a
semantic-truth claim.** `unsupported_claim_rate` uses a simple, fully
deterministic lexical-overlap proxy (normalize both texts, count shared
non-stopword tokens, threshold the overlap ratio) — see `_is_claim_supported`
below for the exact rule. **This is a cheap deterministic faithfulness
proxy, not a semantic truth guarantee.** It cannot detect a claim that
paraphrases its evidence accurately with different words (a false
negative — the proxy under-credits genuinely faithful claims), and it
cannot detect a claim that reuses the cited evidence's own vocabulary while
asserting something the evidence does not actually say (a false positive —
the proxy over-credits lexically-similar-but-false claims). An LLM-as-judge
or embedding-based semantic-entailment check would close both gaps, but
neither is implemented here: no LLM call, no embeddings, no external
evaluation service, no RAGAS or similar framework — the v1 harness stays
deterministic, local, free, and dependency-light, per explicit instruction.
LLM-as-judge is **deferred**, not built, and not scheduled to a specific
future phase — see `documentation/ai-memory/DECISIONS.md`.

**Phase 4's hard citation gate is unchanged and unweakened.**
`torque.ai.narrative._validate_citations` remains the sole authority that
decides whether a `CaseNarrative` is allowed to leave `explain_case` at
all — Phase 5 never relaxes, bypasses, or duplicates that authority; it
only *measures* a narrative that already exists (whether it came from the
real pipeline, having already passed the gate, or was deliberately
constructed by a test to probe the evaluator's own discriminative power).

**Import boundary.** `evaluate_narrative` and its helpers import only
`torque.ai.schemas` and `torque.ai.citations` — nothing capable of writing
anything, exactly like `torque.ai.citations` itself.
`evaluate_retrieval_precision` additionally imports `torque.ai.retrieval`
(Phase 3's own read-only module) and `torque.models`/`sqlalchemy` for the
one DB-touching read it performs. Neither imports `torque.state_machine`,
`torque.coordination`, `torque.events`, `torque.agent_console`,
`torque.execution`, `torque.ingestion`, `torque.policy`,
`torque.diagnosis`, `torque.scoring`, `torque.reconciliation`, or
`torque.promises` — enforced by `tests/test_ai_boundary.py`.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from torque.ai.citations import resolve_citation
from torque.ai.retrieval import DEFAULT_TOP_K, find_precedent
from torque.ai.schemas import (
    ActionEvidence,
    CaseEvidence,
    CaseNarrative,
    CaseSnapshot,
    CounterpartyRelationshipEvidence,
    EvaluationReport,
    EvidenceItem,
    NarrativeClaim,
    PrecedentCase,
    PromiseEvidence,
    TimelineEntry,
)
from torque.models import RevenueLeakCase

#: The overlap ratio (fraction of a claim's own non-stopword tokens that
#: must appear in its cited evidence's tokens) above which a claim is
#: classified "supported." Empirically calibrated — not a statistically
#: validated threshold, but not an arbitrary guess either — against
#: `MockProvider`'s own real claim templates: a genuinely well-grounded
#: claim like "The diagnosed root cause is X." legitimately scores ~0.25-
#: 0.33 against a short, structured evidence-field string (most of a short
#: template sentence is framing words like "the"/"diagnosed"/"is", not
#: repeated evidence content), while the task's own illustrative BAD
#: example ("The merchant requested a full refund immediately.") scores
#: 0.0 against unrelated evidence. `0.2` was chosen as the lowest round
#: value that still classifies every real `MockProvider` claim as
#: supported while leaving a wide, easily-discriminated margin below any
#: genuinely unrelated claim — see the module docstring's "Deterministic
#: v1 methodology" note for why this is a proxy, not a semantic guarantee,
#: regardless of where the cutoff sits.
_OVERLAP_THRESHOLD = 0.2

#: A small, fixed English stopword list — enough to strip the most common
#: low-information words (articles, auxiliary verbs, prepositions) so the
#: overlap check compares content words, not grammar. Deliberately short
#: and inspectable, not an imported corpus/library list.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "was", "were", "are", "be", "been", "being",
        "this", "that", "these", "those", "to", "of", "in", "on", "at", "by",
        "for", "with", "and", "or", "as", "it", "its", "has", "have", "had",
        "not", "no", "yet", "did", "does", "do", "will", "can", "may",
    }
)

#: Splits on anything that is not a word character — punctuation, quotes,
#: whitespace all become separators. Deliberately simple (no stemming, no
#: locale handling): this is a lexical proxy, not an NLP pipeline.
_TOKEN_RE = re.compile(r"[^\w]+")


# --- normalization -----------------------------------------------------


def _normalize_tokens(text: str) -> set[str]:
    """Lowercase, split on non-word characters, drop stopwords and empty
    tokens. Pure, deterministic — same text in, same token set out, every
    time."""
    if not text:
        return set()
    lowered = text.lower()
    tokens = (tok for tok in _TOKEN_RE.split(lowered) if tok)
    return {tok for tok in tokens if tok not in _STOPWORDS}


def _evidence_text(item: EvidenceItem) -> str:
    """A deterministic textual representation of one evidence item, built
    only from that item's own field values — never invented, never fetched
    from anywhere else. Every `torque.ai.schemas` evidence type is handled
    explicitly so a future new type fails loudly (falls through to `""`)
    rather than silently comparing against nothing."""
    if isinstance(item, CaseSnapshot):
        return " ".join(
            str(v)
            for v in (item.status, item.leg_type, item.root_cause_code, item.root_cause_label)
            if v
        )
    if isinstance(item, TimelineEntry):
        return " ".join(str(v) for v in (item.event_type, item.actor, item.reasoning) if v)
    if isinstance(item, ActionEvidence):
        return " ".join(
            str(v)
            for v in (item.action_type, item.channel, item.outcome, item.block_reason)
            if v
        )
    if isinstance(item, PromiseEvidence):
        return " ".join(str(v) for v in (item.status, item.promised_amount) if v)
    if isinstance(item, CounterpartyRelationshipEvidence):
        return " ".join(
            str(v) for v in (item.promise_keeping_rate, item.risk_score) if v is not None
        )
    return ""  # pragma: no cover - exhaustive over the current EvidenceItem union


def _resolve_evidence_text(
    citation_id: str, evidence: CaseEvidence, precedents: list[PrecedentCase]
) -> str | None:
    """The comparable text for one citation id, or `None` if it does not
    resolve against anything supplied. Current-case ids resolve through
    Phase 2's real `resolve_citation`; precedent ids are matched by exact
    `evidence_id` equality against `precedents` (the same posture
    `torque.ai.narrative._validate_citations` already takes — a precedent
    id was already proven resolvable by Phase 3 itself) and use that
    precedent's own `outcome_summary` + `root_cause_code` as its text, since
    the precedent's own full `CaseEvidence` is deliberately not supplied
    here (the Absolute Data-Source Rule: only what was actually given to
    generation)."""
    item = resolve_citation(evidence, citation_id)
    if item is not None:
        return _evidence_text(item)
    for precedent in precedents:
        if precedent.evidence_id == citation_id:
            return f"{precedent.root_cause_code} {precedent.outcome_summary}"
    return None


# --- citation collection (mirrors, does not import, narrative.py) -------


def _collect_claim_citation_ids(narrative: CaseNarrative) -> set[str]:
    """The same set `torque.ai.narrative._validate_citations` computes and
    enforces — deliberately mirrored here, not imported, following the same
    "duplicate + cross-test" discipline `torque.ai.retrieval` already
    established for `torque.state_machine.TERMINAL_STATUSES` (D-141): this
    keeps `evaluation.py` from importing a private symbol out of
    `narrative.py` (a module Phase 5 must not modify — §14 of the Phase 5
    task) while guaranteeing the two never silently drift, because
    `tests/test_ai_evaluation.py::
    test_citation_collection_mirrors_narrative_validation_exactly` compares
    them directly against a range of narratives."""
    ids: set[str] = set()
    ids.update(narrative.current_state.citation_ids)
    ids.update(narrative.root_cause_explanation.citation_ids)
    for entry in (
        *narrative.timeline,
        *narrative.actions_taken,
        *narrative.guardrail_explanation,
    ):
        ids.update(entry.citation_ids)
    ids.update(p.evidence_id for p in narrative.precedent.cases)
    return ids


def _claim_bearing_fields(narrative: CaseNarrative) -> list[NarrativeClaim]:
    """The fields the Phase 5 task names as claim-bearing — `summary` and
    `uncertainty` are deliberately excluded (they carry no `citation_ids`
    field on the schema to measure at all; nothing to include or exclude
    ambiguously)."""
    return [
        narrative.current_state,
        narrative.root_cause_explanation,
        *narrative.timeline,
        *narrative.actions_taken,
        *narrative.guardrail_explanation,
    ]


# --- metric 3: unsupported-claim proxy ----------------------------------


def _is_claim_supported(
    claim: NarrativeClaim, evidence: CaseEvidence, precedents: list[PrecedentCase]
) -> bool:
    """The v1 deterministic lexical-overlap rule (see the module docstring's
    "Deterministic v1 methodology" note for the full caveat):

    1. An uncited claim is never silently supported — always `False`,
       consistent with `citation_coverage` treating it as "not covered"
       (§9 of the Phase 5 task).
    2. Normalize the claim text into a token set. An empty token set (no
       content words at all after stopword removal) has nothing to
       falsify — treated as vacuously supported.
    3. Union the normalized token sets of every cited evidence item's own
       text (`_resolve_evidence_text`); a citation that does not resolve to
       any text contributes nothing.
    4. `True` iff the fraction of the claim's own tokens also present in
       that unioned evidence-token set is >= `_OVERLAP_THRESHOLD`.
    """
    if not claim.citation_ids:
        return False

    claim_tokens = _normalize_tokens(claim.claim)
    if not claim_tokens:
        return True

    evidence_tokens: set[str] = set()
    for citation_id in claim.citation_ids:
        text = _resolve_evidence_text(citation_id, evidence, precedents)
        if text:
            evidence_tokens |= _normalize_tokens(text)

    if not evidence_tokens:
        return False

    overlap_ratio = len(claim_tokens & evidence_tokens) / len(claim_tokens)
    return overlap_ratio >= _OVERLAP_THRESHOLD


# --- public API -----------------------------------------------------------


def evaluate_narrative(
    narrative: CaseNarrative,
    evidence: CaseEvidence,
    precedents: list[PrecedentCase],
    *,
    expected_precedent_found: bool | None = None,
    retrieval_precision_at_k: float | None = None,
) -> EvaluationReport:
    """Score one already-generated `CaseNarrative` against the exact
    evidence/precedent it was generated from.

    Pure: no database, no network, no LLM call, no mutation of any
    argument, deterministic (same inputs -> byte-identical
    `EvaluationReport`, every time).

    `expected_precedent_found` and `retrieval_precision_at_k` are optional
    external ground-truth inputs (from a hand-labeled evaluation fixture) —
    this function cannot determine either from the narrative alone, only
    check consistency against a label it is given. Omit either to leave the
    corresponding report field `None` ("not evaluated"), never a fabricated
    pass.
    """
    precedent_ids = {p.evidence_id for p in precedents}

    def _resolves(citation_id: str) -> bool:
        return citation_id in precedent_ids or resolve_citation(evidence, citation_id) is not None

    used_ids = _collect_claim_citation_ids(narrative)
    flat_ids = {c.evidence_id for c in narrative.citations}
    total_ids = used_ids | flat_ids
    resolvable_ids = {cid for cid in total_ids if _resolves(cid)}
    unresolved_ids = sorted(total_ids - resolvable_ids)
    citation_existence_rate = len(resolvable_ids) / len(total_ids) if total_ids else 1.0

    claim_fields = _claim_bearing_fields(narrative)
    total_claims = len(claim_fields)
    cited_claims = sum(1 for c in claim_fields if c.citation_ids)
    citation_coverage = cited_claims / total_claims if total_claims else 1.0

    unsupported_count = sum(
        0 if _is_claim_supported(c, evidence, precedents) else 1 for c in claim_fields
    )
    unsupported_claim_rate = unsupported_count / total_claims if total_claims else 0.0

    no_precedent_correct = (
        None
        if expected_precedent_found is None
        else narrative.precedent.found == expected_precedent_found
    )

    return EvaluationReport(
        citation_existence_rate=citation_existence_rate,
        citation_coverage=citation_coverage,
        unsupported_claim_rate=unsupported_claim_rate,
        no_precedent_correct=no_precedent_correct,
        retrieval_precision_at_k=retrieval_precision_at_k,
        total_claims=total_claims,
        cited_claims=cited_claims,
        total_citations=len(total_ids),
        resolvable_citations=len(resolvable_ids),
        unresolved_citation_ids=unresolved_ids,
        unsupported_claim_count=unsupported_count,
        evaluated_precedent_cases=len(narrative.precedent.cases),
    )


def evaluate_retrieval_precision(
    session: Session,
    merchant_id: str,
    case: RevenueLeakCase,
    relevant_case_ids: set[str],
    *,
    top_k: int = DEFAULT_TOP_K,
) -> float:
    """Precision@K for `torque.ai.retrieval.find_precedent` against an
    independently hand-labeled relevance set (`relevant_case_ids` — never
    derived from the retrieval algorithm itself, per §11 of the Phase 5
    task).

    Deliberately separate from `evaluate_narrative` — this is the one
    Phase 5 function that touches a database (a single read-only call into
    Phase 3's own `find_precedent`); `evaluate_narrative` never does and
    never calls this. Returns `1.0` when nothing was relevant and nothing
    was retrieved (a correct empty result), `0.0` when something was
    relevant but nothing was retrieved, and the standard
    `|retrieved ∩ relevant| / |retrieved|` otherwise.
    """
    results = find_precedent(session, merchant_id, case, top_k=top_k)
    if not results:
        return 1.0 if not relevant_case_ids else 0.0
    retrieved_ids = {r.case_id for r in results}
    return len(retrieved_ids & relevant_case_ids) / len(retrieved_ids)


__all__ = ["evaluate_narrative", "evaluate_retrieval_precision"]
