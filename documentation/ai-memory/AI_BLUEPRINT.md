# AI_BLUEPRINT.md — the Torque AI layer

**Location note:** this file lives in `documentation/ai-memory/` alongside
`ARCHITECTURE.md` / `DECISIONS.md` / `MILESTONES.md` / `INVARIANTS.md` /
`DEFERRED.md`, following this project's existing convention that everything
about *why* the system looks the way it does lives in one directory the
maintainer reads first. No deviation from the existing location convention
was needed.

**Branch:** this entire file, and every capability it describes as
implemented, lives on the `ai-layer` branch — never on `main` until the
Main-Branch Integration Gate (§18) passes and the maintainer explicitly
merges it. `main` is unmodified by any of this work.

**Status of this document:** this is the reviewed architecture for the
Torque AI layer, reconstructed from (a) a prior AI-architecture research
pass over this repository, (b) a prior phase-by-phase implementation
blueprint produced in conversation, and (c) an explicit sequencing
correction supplied for AI Phase 2, all grounded directly against the
source tree rather than assumed. Where a decision was genuinely established
it is marked **LOCKED**; where this document proposes an approach without a
maintainer sign-off yet it is marked **RECOMMENDED**; work explicitly not
being built now is marked **DEFERRED**; and any choice this document
declines to make unilaterally is marked **NEEDS HUMAN DECISION**. Nothing
below is fabricated to fill a gap — an absent decision is marked as absent,
not guessed.

> **Sequencing correction (superseding this document's earlier phase
> numbering):** an earlier version of this file, written after Phase 0+1,
> numbered "Phase 2" as retrieval. That was **incorrect** — the authoritative
> sequence, confirmed for this milestone, is:
>
> ```
> Phase 0 — AI architectural isolation
> Phase 1 — AI read model / evidence interface
> Phase 2 — Evidence normalization + citation model
> Phase 3 — Retrieval / precedent engine
> Phase 4 — LLM case explanation
> Phase 5 — Faithfulness / evaluation
> Phase 6 — Agent Console integration
> Phase 7 — Shadow ML
> Phase 8 — Hardening
> Phase 9 — Demo polish
> ```
>
> Every phase number in this document now reflects that sequence. See
> `documentation/ai-memory/MILESTONES.md`'s "AI Phase 2" section for the
> correction as recorded in the append-only milestone history.

---

## Current Implementation Status

```
Phase 0 — AI architectural isolation                COMPLETE
Phase 1 — AI read model / evidence interface          COMPLETE
Phase 2 — Evidence normalization + citation model      COMPLETE
Phase 3 — Retrieval / precedent engine                  NOT STARTED
Phase 4 — LLM case explanation                           NOT STARTED
Phase 5 — Faithfulness / evaluation                       NOT STARTED
Phase 6 — Agent Console integration                        NOT STARTED
Phase 7 — Shadow ML                                         NOT STARTED
Phase 8 — Hardening                                          NOT STARTED
Phase 9 — Demo polish                                         NOT STARTED
```

**What exists in the repository right now, concretely:** the `src/torque/ai/`
package — `__init__.py`, `exceptions.py`, `config.py`, `schemas.py`,
`evidence.py` (Phase 0+1), and `citations.py` (Phase 2) — plus its test
suite (`tests/test_ai_boundary.py`, `tests/test_ai_config.py`,
`tests/test_ai_evidence.py`, `tests/test_ai_citations.py`). The package's
public capabilities are: `torque.ai.evidence.gather_case_evidence` (a
read-only function projecting one case's authoritative Torque state into
typed, redacted, citation-referenced DTOs) and `torque.ai.citations.
resolve_citation` / `all_evidence_items` / `citation_for` (a pure,
no-database citation-resolution primitive operating on that projection).
There is no retrieval, no embedding, no LLM call, no citation-bearing
generated prose, no shadow ML model, and no API endpoint. See "Deferred
Work" in the Phase 2 completion report for the exact, unimplemented list.

No phase beyond 0, 1, and 2 is marked complete merely because its
architecture is documented below — everything from Phase 3 onward in this
file is a plan, not a report of what exists.

---

## 1. Purpose

Give Torque's human reviewers (the Agent Console, Module 10) a grounded,
citation-backed explanation of any case's history and current state, and —
once real resolved-case volume justifies it — a small, explicitly
observational proof of the learned-model upgrade path the blueprint itself
already named (§8.4). At no point does the AI layer make, or influence, a
Torque decision. It reads; Torque decides.

## 2. Current-State Assumptions

Verified directly against the repository (`git log --oneline -1` =
`a0fb0f3` "Module 12a: close the autonomous loop", committed, `main` clean
at the time `ai-layer` was forked):

- Torque is a 12-module (+ 12a), deterministic, rule-based revenue-recovery
  engine. Diagnosis (Module 3), recovery scoring (Module 8), policy
  selection (Module 4), and incrementality measurement (Module 9b) are all
  closed-form functions or classical statistics — **no machine learning
  exists anywhere in the codebase today.**
- The only outcome data that exists is a 16-case seeded demo dataset
  (`torque.demo.seed.seed_demo`) plus whatever cases the one-click scenario
  injectors (`torque.demo.scenarios`) create. There is no bulk historical
  dataset, no real merchant traffic (channel adapters are still stubs —
  `run_action` performs no real I/O), and no calibration history for the
  diagnosis-confidence threshold or the recovery-scoring warm-start
  multiplier (both are stated, unvalidated defaults per U-09).
- The blueprint itself already names an exact future learned model — XGBoost
  + SHAP with T-learner/X-learner uplift meta-learners — gated on **500+
  resolved cases**, and names the exact feature set it would train on
  (`leg_type, root_cause_code, diagnosis_confidence, amount_at_risk,
  days_since_failure, promise_keeping_rate, risk_score,
  network_directive.tier, mandate_type` — Blueprint §8.4). This is real,
  correct, and explicitly "roadmap," not built.
- Torque's frontend is a vanilla-JS single-page shell (`src/torque/ui/static/`
  — `index.html`, `torque.css`, `torque.js`), no build step, no framework.
- Torque's API surface is a set of thin FastAPI routers over pure-Python
  domain modules, uniformly using `Depends(get_db)`
  (`src/torque/api/{health,webhooks,checkout_injection,reporting,
  agent_console,demo,ui}.py`).
- `pyproject.toml` carries zero AI/ML/HTTP-to-LLM dependencies as of Phase
  0-2 (`sqlalchemy`, `alembic`, `psycopg`, `pydantic`/`pydantic-settings`,
  `fastapi`, `uvicorn`, `celery`, `redis` only). **No dependency was added**
  — everything needed already exists in the standard library or `pydantic`.
- `CaseEvent` is Torque's sole audit/history mechanism (append-only,
  DB-trigger + guard enforced, INV-02). Any AI evidence representation must
  be *derived from* it, never a second, competing history.

## 3. AI Architectural Principles

Adopted as a hard constraint, with no contradiction found in the repository
that would justify relaxing it:

```
Deterministic Torque decides.
AI reads and explains.
AI does not mutate Torque business state.
```

Enforced, not merely stated:

1. **Package isolation.** All AI code lives under `src/torque/ai/`.
2. **One-directional dependency, enforced by a static test.**
   `torque.ai.*` may read via `torque.db.scoped.TenantScope`,
   `torque.models.*`, `torque.enums`, `torque.exceptions`. It may **never**
   import `torque.state_machine`, `torque.coordination`, `torque.events`,
   `torque.agent_console`, `torque.execution`, `torque.ingestion`,
   `torque.policy`, `torque.diagnosis`, `torque.scoring`,
   `torque.reconciliation`, `torque.promises`, or `torque.api` —
   `tests/test_ai_boundary.py` parses the AI package's own source with `ast`
   (no execution) and fails the build if any forbidden import appears,
   plus a second, independent substring sweep for raw write-shaped calls
   (`.add(`, `.delete(`, `.commit(`, raw SQL mutation keywords). This
   applies to `torque.ai.citations` (Phase 2) exactly as it applies to
   `torque.ai.evidence` — the boundary test covers the whole package, not
   per-module allowlists.
3. **No new source of truth.** AI evidence is always re-derived on demand
   from `CaseEvent`/`RevenueLeakCase`/`Action`/`PromiseToPay` at request
   time — mirroring Module 9's own INV-58 posture. No AI-specific
   case-history table exists or is planned. Citation resolution (Phase 2)
   does not persist anything either — it operates purely on an
   already-gathered, in-memory evidence set.
4. **DTOs only, never ORM rows.** `torque.ai.schemas` objects are the only
   thing that ever crosses out of `torque.ai.evidence` — see §7.

## 4. Deterministic vs AI Responsibility Boundary

| Capability | Owner | AI's relationship to it |
|---|---|---|
| Case state transitions | `torque.state_machine.transition_case` | AI never calls it; forbidden import |
| Diagnosis | `torque.diagnosis.*` | AI reads the *result* (`root_cause_code`, `diagnosis_confidence`) off the case row; never computes or influences a diagnosis |
| Recovery scoring | `torque.scoring.score.*` | AI reads the *result* (`recovery_score`, `recovery_score_breakdown`) off the case row; the future shadow model (Phase 7) computes its own, separate, never-consumed number |
| Guardrails | `torque.coordination.guardrail_engine.GuardrailEngine` | AI never calls it; reads only the *outcome* of a guardrail decision via `Action.outcome`/`block_reason` |
| Action execution | `torque.execution.*` | AI never calls it; forbidden import |
| Playbook selection | `torque.policy.*` | AI never calls it; forbidden import |
| Human override (resolve/pause) | `torque.agent_console.resolve.*` | AI never calls it; forbidden import |
| Audit history | `torque.models.CaseEvent` (append-only) | AI reads it; never writes it; never invents a parallel history |
| Citation identity | `torque.ai.citations` (Phase 2) | Derived entirely from already-authoritative Torque primary keys/sequences; no new identity is minted, nothing is persisted |

## 5. Target Architecture

```
                    Deterministic Torque Core
        (ingestion, diagnosis, scoring, policy, execution,
                guardrails, state machine)
              -- UNCHANGED BY THIS PROGRAM --
                            |
                            | read-only (TenantScope.select/.get/.all only)
                            v
                     torque.ai  (this package)
      +----------------------------------------------------+
      |  IMPLEMENTED (Phase 0-2):                            |
      |    exceptions.py  config.py  schemas.py  evidence.py  |
      |    citations.py                                       |
      |  NOT YET BUILT (Phase 3+):                            |
      |    retrieval.py  prompts.py  providers/  narrative.py |
      |    evaluation.py  shadow/                              |
      +----------------------------------------------------+
                            |
                            | (future) structured, cited output only
                            v
                torque.api.ai  (future — does not exist yet)
                            |
                            v
              torque.ui.static  (future — no changes yet)
```

## 6. AI Component Boundaries

```
src/torque/ai/
├── __init__.py       IMPLEMENTED — package boundary statement
├── exceptions.py      IMPLEMENTED — AIError, EvidenceNotFoundError
├── config.py           IMPLEMENTED — AISettings (TORQUE_AI_ENABLED, default False)
├── schemas.py           IMPLEMENTED — evidence DTOs (§7) + Citation/EvidenceItem (Phase 2)
├── evidence.py            IMPLEMENTED — gather_case_evidence()
├── citations.py            IMPLEMENTED (Phase 2) — resolve_citation(), all_evidence_items(), citation_for()
├── retrieval.py              NOT BUILT (Phase 3)
├── prompts.py                  NOT BUILT (Phase 4)
├── providers/                    NOT BUILT (Phase 4)
├── narrative.py                    NOT BUILT (Phase 4)
├── evaluation.py                     NOT BUILT (Phase 5)
└── shadow/                             NOT BUILT (Phase 7)
```

## 7. Read-Only Evidence Architecture & Citation Model

**Implemented, Phase 1.** `torque.ai.evidence.gather_case_evidence(session,
*, merchant_id, case_id) -> CaseEvidence` is the single entry point.

**Field-by-field allowlist actually implemented** (anything not listed is
not read):

| Source table | Exposed | Excluded |
|---|---|---|
| `RevenueLeakCase` | `case_id, leg_type, status, amount_at_risk, root_cause_code, root_cause_label, diagnosis_confidence, network_directive_tier, opened_at, closed_at, recovery_type, recovered_amount, recovery_score, recovery_score_breakdown, escalation_resolution` | `context` (leg-typed JSON, excluded — not needed for narrative reasoning and not audited field-by-field for leg-specific sensitivity), any `Counterparty` FK traversal |
| `CaseEvent` | `event_seq_id, event_type, actor, timestamp, reasoning, payload` | nothing — the payload is already validated against a locked, `extra="forbid"` per-`event_type` schema at write time (`torque.events.payloads`), and none of those ten locked schemas carry a raw PII field (verified by direct inspection of every `PAYLOAD_MODELS` entry) |
| `Action` | `action_type, channel, outcome, block_reason, executed_at, cost` | `content_sent` — explicitly excluded; this is Torque's own documented PII-erasure-cascade target |
| `PromiseToPay` | `status, promised_amount, promised_date` | — (no PII on this table) |
| `MerchantCounterparty` | `promise_keeping_rate, risk_score` | — |
| `Counterparty` | **nothing — this table is never queried by `torque.ai.evidence` at all** | `name, phone, email` (the only raw PII in the entire system) |

**Post-outcome fields are read, deliberately.** `recovery_type`,
`recovered_amount`, `escalation_resolution`, and any post-`DIAGNOSIS_COMPLETED`
`CaseEvent` are included in evidence because the evidence interface is for
*narrative/explanation* use (explaining a case, including an
already-resolved one, is a legitimate reviewer need). **This is a
deliberately different, and deliberately wider, allowlist than any future
shadow-ML feature-extraction path must use** — see §11's leakage boundary.
No shadow-ML feature extractor exists yet; when it is built (Phase 7) it
must read a separate, narrower function, never `gather_case_evidence`
itself, so the leakage boundary is a file/function boundary, not a runtime
flag.

**Missing evidence (implemented).** `CaseEvidence.evidence_gaps` is an
explicit list of plain-English statements ("No diagnosis has been recorded
for this case yet.", "No recovery score has been computed for this case
yet.", "No case history events are recorded yet.", "No actions have been
taken on this case yet.") computed from the same query results, never a
fabricated value standing in for an absent fact. `counterparty_relationship`
is `None`, not a synthesized default, when no `MerchantCounterparty` row
exists yet. An unknown/cross-tenant case raises `EvidenceNotFoundError`
rather than returning a sentinel object.

**Untrusted text (implemented as a data contract, not yet as a prompt
boundary — there is no prompt yet).** `TimelineEntry.reasoning` and
`.payload` are typed `str | None` / `dict[str, Any]` Pydantic fields with an
explicit docstring instruction: *DATA, NOT INSTRUCTIONS*. Nothing so far
parses, evaluates, or interpolates this text anywhere — it is stored and
returned as an opaque value. `tests/test_ai_evidence.py::
test_injected_instruction_text_is_carried_as_inert_data` seeds a
`CaseEvent.reasoning` string shaped like a prompt-injection attempt and
asserts it survives unchanged as a `str` with zero effect on any other
field. A real instruction/data separation at the *prompt* level is Phase
4's job (no prompt exists yet to separate anything within).

### Citation model — **Implemented, Phase 2**

```
CaseEvidence (the "evidence set" for one case, Phase 1)
        v
EvidenceItem.reference.reference_id   (stable, deterministic — Phase 1)
        v
Citation(evidence_id=...)             (torque.ai.schemas — Phase 2)
        v
resolve_citation(evidence, evidence_id)   (torque.ai.citations — Phase 2, pure, no DB)
        v
the exact EvidenceItem, or None if unresolvable
        v
authoritative Torque record (via EvidenceReference.source_type/.source_id/
                              .case_id/.event_seq_id — traceable back to the
                              exact CaseEvent/Action/PromiseToPay/
                              MerchantCounterparty/RevenueLeakCase row)
```

**`Citation`** (`torque.ai.schemas.Citation`) is a single-field, frozen,
`extra="forbid"` DTO — `evidence_id: str` only. Deliberately minimal: it
names *which* evidence a future claim points to, not *what claim* it makes
— that belongs to whatever future object carries generated prose (Phase 4+,
not built).

**`EvidenceItem`** is a `typing` union of the five evidence-item types Phase
1 already produces (`CaseSnapshot | TimelineEntry | ActionEvidence |
PromiseEvidence | CounterpartyRelationshipEvidence`) — no new evidence type
was invented.

**`reference_id` scheme — preserved unchanged from Phase 1.**
`f"{source_type}:{source_id}"`, where `source_id` is always drawn from an
authoritative Torque primary key or sequence value. Evaluated against the
four required properties (uniqueness within an evidence set, stability
across repeated gathering, deterministic derivation, source traceability)
and found to already satisfy all four — in fact more strongly than required,
since every underlying id (`CaseEvent.event_seq_id`, `Action.action_id`,
`PromiseToPay.promise_id`, `MerchantCounterparty.id`, `RevenueLeakCase.
case_id`) is already globally unique, not merely unique within one case.
**Not replaced** with the illustrative `f"{source_type}:{case_id}:
{event_seq_id or action_id}"` form — that would be redundant (`case_id` is
already a separate field on `EvidenceReference`) for zero uniqueness
benefit. See `documentation/ai-memory/DECISIONS.md` D-140.

**`CaseSnapshot` gains a `reference` field — a Phase 1 gap closed, not a
redesign.** `SourceType` already reserved a `"case"` literal in Phase 1, but
nothing constructed one; the case's own current-state facts (status, root
cause, recovery score, ...) had no citation target. This is purely additive
— no existing field on any DTO was renamed, removed, or retyped — and is
exactly what Phase 2 exists to close. See D-140.

**`resolve_citation(evidence: CaseEvidence, evidence_id: str) -> EvidenceItem
| None`** (`torque.ai.citations`) is pure: no `Session`, no database, no
I/O of any kind. It searches only the one `CaseEvidence` object it is
handed — an id from a different case's (or a different tenant's) evidence
set never resolves, because no other evidence set is ever consulted. Never
raises for an unknown, fabricated, malformed, or empty id — `None` is the
only failure signal, so a future faithfulness-evaluation layer (Phase 5) can
treat it as "unsupported claim" data rather than a control-flow exception.
See INV-61.

## 8. Planned Retrieval Architecture — **NOT BUILT** (Phase 3)

**RECOMMENDED**, not yet implemented: Postgres-native full-text search
(`tsvector`/`plainto_tsquery`) over `CaseEvent.reasoning` + `root_cause_label`,
combined with a `(merchant_id, leg_type, root_cause_code)` metadata filter as
the primary relevance signal. **No vector database, no embedding model, no
ANN index** — the current corpus (dozens to low hundreds of cases) does not
justify infrastructure that exists to make search sub-linear over millions
of rows. An empty precedent result is a first-class, expected outcome, not
an error, for a case whose root cause has no prior match. See the prior
research phase's architecture comparison for the full evaluated-alternatives
table (Postgres FTS / BM25 / embeddings+brute-force / vector DB), reproduced
in spirit here but not re-litigated — nothing has changed about the
corpus-size argument since that research.

## 9. Planned LLM Architecture — **NOT BUILT** (Phase 4)

**RECOMMENDED**, not yet implemented: a provider-agnostic `LLMProvider`
interface (`structured_generate(system, user, schema) -> BaseModel`) with at
minimum three implementations — a real provider (Anthropic, **NEEDS HUMAN
DECISION** on budget/key provisioning), a local/free provider (e.g.
Ollama-served small model) for network-independent dev/CI, and a
`MockProvider` returning fixed, deterministic output so the entire AI test
suite never requires network access or an API key by default — the same
discipline the existing suite already applies to Celery
(`celery_task_always_eager`). Evidence is serialized into a clearly
delimited, explicitly labeled block, separated at the transport level
(system vs. user message) wherever the provider supports it, with the model
instructed in the system message to treat that block as data. Generated
claims will carry `citation_ids` resolved through Phase 2's
`resolve_citation` before ever reaching a caller. No prompt has been
written; no provider integration exists.

## 10. Planned Shadow ML Architecture — **NOT BUILT** (Phase 7)

**RECOMMENDED**, not yet implemented, and explicitly gated behind Phases 3-6
landing first (it has no dependency on retrieval/LLM work technically, but
sequencing it after keeps the riskier, more novel narrative-generation work
reviewed first). Target: binary `recovered` (`status in {RECOVERED,
CANCELLED}`, matching Module 9b's own intent-to-treat definition exactly).
Features: **exactly** the Blueprint §8.4 named set, read through a
*separate, narrower* feature-extraction function that never shares code with
`gather_case_evidence` (§11). Model: XGBoost + SHAP, per Decision F / §8.4.
**Never consumed by `priority()`, `human_queue.priority`, playbook
selection, diagnosis, or execution** — purely observational, with a
required, non-optional `n_training_cases` + `disclaimer` field in its output
schema so the UI cannot render a number without the caveat attached.

## 11. Security Model

Implemented (Phase 0-2):

- **Static import-boundary test**, `tests/test_ai_boundary.py` — see §3
  item 2. This is the load-bearing enforcement mechanism; everything else in
  this section is defense-in-depth around it. Covers the entire `torque.ai`
  package, `citations.py` included.
- **Substring write-call sweep** — `tests/test_ai_boundary.py::
  test_ai_package_writes_nothing_at_the_source_level` — an independent,
  deliberately crude second signal (no `.add(`, `.delete(`, `.commit(`, or
  raw SQL mutation keyword anywhere in `src/torque/ai/`).
- **Read-only by construction, not by a runtime guard** — `torque.ai.evidence`
  never calls `session.add`/`.delete`/`.commit`; it only calls
  `TenantScope.select`/`.get` and `session.scalars(...)`. `torque.ai.
  citations` goes further still: it has no database-access capability to
  even accidentally exercise — it imports nothing but `torque.ai.schemas`.
  There is currently no forbidden write *capability* to additionally
  firewall at the ORM layer, because none of the AI package's code
  constructs a write in the first place.

Planned, **NOT YET BUILT**:

- A dedicated read-only DB session/role for the future API layer (Phase 6) —
  **NEEDS HUMAN DECISION** on whether a Postgres role with `SELECT`-only
  grants is provisioned (a one-time DB-admin action outside Alembic's normal
  migration flow) versus relying on the import-boundary test alone.
- Prompt-injection defenses at the *prompt* level (Phase 4 — no prompt
  exists yet). The *data contract* (§7's "untrusted text" note) and the
  citation-resolution primitive it will be validated through (§7's
  "Citation model") are already in place so Phase 4/5 have something
  correct to build on.

**Leakage boundary (documented now, enforced by file separation once Phase 7
exists).** `gather_case_evidence` deliberately returns post-outcome fields
(§7). A future shadow-ML feature extractor must read a disjoint, narrower
function reading only the Blueprint §8.4 field set — this is a design
commitment recorded here so Phase 7 cannot silently reuse the wider
evidence function and reintroduce leakage.

## 12. Prompt-Injection Model — **foundation only, no prompt exists yet**

Implemented: the schema-level data contract (§7's "untrusted text" note),
the citation-resolution primitive a future faithfulness layer will validate
generated claims against (§7's "Citation model"), and a passing adversarial
test proving `CaseEvent.reasoning` text shaped like an injection attempt has
zero effect on the structure of the evidence DTO it lands in. **Not yet
built:** the actual system/user message separation, the delimited
serialization format, and the adversarial test suite against a real or mock
LLM (all Phase 4+ — see the prior research phase's full treatment of this
topic for the target design, not repeated here since no code implements it
yet).

## 13. Multi-Tenancy / Data-Isolation Requirements

Implemented and tested (Phase 1-2):

- Every read in `torque.ai.evidence` goes through `TenantScope` — `.get()`
  for the case itself (returns `None`, not another tenant's row, for a
  cross-tenant id — INV-01), `.select()` for `Action`/`PromiseToPay`/
  `MerchantCounterparty` (all genuinely `TenantScoped` models).
- `CaseEvent` (not `TenantScoped` at the column level — it carries no
  `merchant_id`) is filtered by the already-ownership-verified `case_id`,
  the identical justification `torque.reporting.metrics` documents under
  INV-58 for this same table.
- `merchant_id` is sourced from the caller's explicit keyword argument only —
  never inferred, never defaulted, never read from any evidence content.
- `tests/test_ai_evidence.py::test_cross_tenant_case_is_invisible` proves a
  case created under merchant A raises `EvidenceNotFoundError` when queried
  through merchant B's scope.
- **Citation resolution (Phase 2) cannot become a tenant-isolation bypass.**
  `resolve_citation` only ever searches the one `CaseEvidence` object it is
  given — there is no global registry, no cross-case index, and no database
  access from `torque.ai.citations` at all. `tests/test_ai_citations.py::
  test_cross_tenant_evidence_id_does_not_resolve` proves an evidence id from
  merchant A's case does not resolve against merchant B's evidence set.
- **`Counterparty` (the one global, non-tenant-scoped PII table) is never
  queried by this package at all** — there is no code path that could leak
  PII across tenants because there is no code path that reads PII, full
  stop.

Not yet relevant: cross-merchant precedent retrieval does not exist (Phase
3). When it is built, it must remain single-merchant only in its first
version — Module 9b's one narrow, reviewed cross-merchant SUTVA read is not
a precedent (no pun intended) the AI layer inherits automatically.

## 14. Phase Roadmap

| Phase | Objective | Status |
|---|---|---|
| 0 | AI architectural isolation — package boundary, feature flag, static enforcement test | **COMPLETE** |
| 1 | AI read model / evidence interface | **COMPLETE** |
| 2 | Evidence normalization + citation model (`Citation`, `resolve_citation`, stable evidence ids) | **COMPLETE** |
| 3 | Retrieval / precedent engine (Postgres FTS + metadata filter) | NOT STARTED |
| 4 | LLM case explanation (provider-agnostic, evidence-grounded, citation-bearing) | NOT STARTED |
| 5 | Faithfulness / evaluation harness (validates generated citations via Phase 2's `resolve_citation`) | NOT STARTED |
| 6 | Agent Console integration (new read-only API route + UI panel) | NOT STARTED |
| 7 | Shadow ML model (observational only) | NOT STARTED |
| 8 | Hardening (adversarial + failure-mode testing) | NOT STARTED |
| 9 | Demo polish + documentation | NOT STARTED |

## 15. Phase Dependencies

```
Phase 0 (isolation, boundary test)
   |
Phase 1 (evidence read model)
   |
Phase 2 (evidence normalization + citation model)   <- YOU ARE HERE (complete)
   |
Phase 3 (retrieval / precedent)
   |
Phase 4 (LLM case explanation) <---+
   |                                |
Phase 5 (faithfulness evaluation)   |    (consumes Phase 2's resolve_citation
   |                                |     directly — this is why citations had
Phase 6 (Agent Console integration) |     to exist before generation, not after)
   |                                |
Phase 7 (shadow ML) -- depends only on Phase 1, mergeable in parallel with 3-6
   |
Phase 8 (hardening) -- depends on everything above
   |
Phase 9 (demo polish)
   |
Final AI Integration Gate (main-branch merge eligibility)
```

## 16. Testing / Evaluation Strategy

Implemented for Phase 0-2 (38 AI-specific tests, all passing — see the
Phase 2 completion report for exact file/test names): architecture/boundary
tests (static import-graph check + write-call substring sweep across the
whole package, including `citations.py`), evidence-shape tests (snapshot
correctness, timeline ordering, citation-reference resolvability),
tenant-isolation tests, PII-exclusion tests (both schema-shape and
content-substring sweeps), missing-evidence tests, one untrusted-text/
injection-resilience test, and (Phase 2) citation-schema validation, id
uniqueness, id stability across repeated gathering, exact resolution for
every evidence type, fabricated/malformed/cross-case/cross-tenant
non-resolution, and multi-evidence-type resolution. Full existing
regression suite (1230 pre-existing tests) re-run and green alongside every
new AI test added since.

Not yet built: retrieval-relevance evaluation, citation-precision/coverage
metrics *for generated prose* (Phase 2 validates the resolution primitive
itself, not yet any actual generated claim — there is no generated claim
yet), faithfulness/groundedness scoring, adversarial LLM-facing prompt-
injection tests, shadow-ML leakage/calibration tests — all Phase 3+.

## 17. Git / Branch Strategy

**LOCKED by explicit instruction for this program:** all AI work happens on
the `ai-layer` branch (confirmed current branch for every phase implemented
so far), forked from a clean, fully-committed `main`. `main` receives no
changes from this program until an explicit, maintainer-performed merge
after the Integration Gate (§18) passes. This document does not perform any
Git operation — branch creation, commits, and merges are the maintainer's
own actions throughout. No sub-branches were created for Phase 2; all work
landed directly on `ai-layer`, per explicit instruction for this milestone.

**RECOMMENDED** (not yet exercised): one phase per feature branch off
`ai-layer` (`ai-layer/phase-N-<slug>`), each independently reviewable,
merged into `ai-layer` in dependency order — an option for the maintainer to
adopt for future phases; Phase 0-2 were each built directly on `ai-layer`
instead, per explicit instruction each time.

## 18. Main-Branch Integration Gate

**RECOMMENDED**, unexercised (no merge into `main` has been proposed or
performed). Before `ai-layer` is eligible to merge into `main`:

- [ ] Full existing regression suite green, unmodified.
- [ ] `uv run ruff check .` clean repository-wide.
- [ ] `alembic upgrade head` succeeds; zero new migrations introduced by the
      AI program (true through Phase 2: no migration exists under this work).
- [ ] Every AI-specific test file green.
- [ ] `tests/test_ai_boundary.py` green — the forbidden-import and
      forbidden-write-call checks both pass.
- [ ] `git diff main...ai-layer` touches none of: `state_machine.py`,
      `models/guards.py`, `coordination/guardrail_engine.py`,
      `events/case_event_writer.py`, `agent_console/resolve.py`, any
      `execution/*.py`, `scoring/score.py`'s write functions, or any
      existing migration file.
- [ ] Demo usability: a human can use whatever AI-facing feature exists,
      unaided (not yet applicable — no UI-facing feature exists).
- [ ] `documentation/ai-memory/{ARCHITECTURE,DECISIONS,MILESTONES,DEFERRED,
      INVARIANTS}.md` updated to reflect the new module(s), in this
      project's own established style (this document + the accompanying
      decision/invariant/milestone entries are the Phase 0-2 instance of
      that requirement).

## 19. Demo Architecture

Not yet applicable — no user-visible AI capability exists (Phase 0-2 is
entirely backend, read-only, invisible to any UI). See the prior research
phase's full demo narrative for the target end-to-end story once Phase 6
lands; not reproduced here since it describes a UI flow that does not exist
yet.

## 20. Decision Register

| ID | Decision | Recommended / Locked | Status |
|---|---|---|---|
| D-AI-05 | Evidence schema: typed, redacted DTOs, never raw ORM rows | **LOCKED** | Implemented (`torque.ai.schemas`) |
| D-AI-06 | Citation schema: structured `EvidenceReference` with a stable `reference_id`, not free-text | **LOCKED** | Implemented |
| D-AI-08 | Tenant isolation: reuse `TenantScope` exactly, no second facade | **LOCKED** | Implemented |
| D-AI-15 | Feature flag: `TORQUE_AI_ENABLED`, default `False`, same `BaseSettings` pattern as `torque.config` | **RECOMMENDED** | Implemented (`torque.ai.config.AISettings`) |
| D-AI-17 (part 1) | Read-only enforcement: static import-boundary test | **LOCKED** (implemented, non-negotiable per this program's instructions) | Implemented |
| D-AI-17 (part 2) | Read-only enforcement: dedicated Postgres read-only DB role | **NEEDS HUMAN DECISION** | Not built — Phase 6+ |
| D-140 | Citation contract: preserve Phase 1's `reference_id` scheme; make `CaseSnapshot` citable; keep `Citation` to one field; keep `resolve_citation` pure | **LOCKED** (implemented; see `DECISIONS.md`) | Implemented |
| D-AI-01 | Retrieval architecture: Postgres FTS + metadata filter, no vector DB | **RECOMMENDED** | Not built — Phase 3 |
| D-AI-03 | LLM provider: Anthropic primary + local/mock fallback | **NEEDS HUMAN DECISION** (API budget/key) | Not built — Phase 4 |
| D-AI-09 | Persistence vs. stateless generation: regenerate narratives on request, no caching table | **RECOMMENDED** | Not applicable yet — Phase 4 |
| D-AI-11 | Shadow-model inclusion: build, strictly observational | **RECOMMENDED** | Not built — Phase 7 |
| D-AI-14 | Branch strategy: `ai-layer`, forked from clean `main`, no sub-branches | **LOCKED** (satisfied) | Satisfied |
| D-AI-18 | `pyproject.toml` `ai` extras group | **DEFERRED** — not created; no dependency needed it yet | Deferred to whichever phase first needs a new dependency |

## 21. Risk Register

| Risk | Status at Phase 0-2 |
|---|---|
| AI write-path creep | Mitigated by the static, CI-enforced import-boundary test — present and green, covers `citations.py` too |
| PII leakage into AI evidence | Mitigated by an explicit allowlist + passing content-substring tests; `Counterparty` is never queried |
| Cross-tenant retrieval / citation resolution | Mitigated by exclusive `TenantScope` use in evidence-gathering + a passing cross-tenant evidence test, and by `resolve_citation`'s complete inability to reach any evidence set other than the one it is given (no DB access at all) + a passing cross-tenant citation test |
| Fabricated/placeholder "evidence" standing in for missing data | Mitigated — `evidence_gaps` is explicit, `None` stays `None`, tested |
| A citation silently resolving to the wrong record | Mitigated — exact-match-only resolution, scoped to one evidence set, tested against fabricated/malformed/cross-case/cross-tenant ids (INV-61) |
| Prompt injection | Data contract in place (reasoning/payload typed as inert data) and one adversarial test passing; the real risk surface (an actual prompt) does not exist yet |
| Hallucination, unsupported claims, shadow-model overclaiming, provider outage, latency | Not yet applicable — no LLM call, no shadow model exists |

## 22. Explicit Non-Goals

Unchanged from the prior research phase, reaffirmed here: no agentic/
autonomous AI action-taking; no LLM-driven diagnosis, playbook selection, or
guardrail decision; no production consumption of any future shadow-model
output by a deterministic consumer; no cross-merchant precedent retrieval in
v1; no new audit/history mechanism; no vector database or paid
infrastructure in v1; no migration, no schema change, anywhere in this
program to date; no global citation registry or citation database table; no
change to `main` until the Integration Gate passes and the maintainer
performs the merge.

## 23. Future Path Toward the 500+ Resolved-Case Learned Model

Unchanged from the prior research phase: **TODAY** is Phase 0-2 as
implemented — a read-only evidence foundation with a resolvable citation
primitive, nothing predictive, nothing generated. **Phase 3-9** (this
document's roadmap) is what's worth building for a hackathon demo —
retrieval-grounded narrative, validated against Phase 2's citation contract,
plus an honestly-caveated shadow model. **FUTURE PRODUCTION** requires real
channel adapters shipping, real merchant traffic accumulating real outcomes,
and crossing the blueprint's own 500-resolved-case threshold (Blueprint
§8.4) before any learned signal is even considered for wiring into
`priority()` — and that wiring, if it ever happens, is its own future,
separately approved phase, not something this program authorizes.
