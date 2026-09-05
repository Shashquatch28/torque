# Technical Report

A concise engineering account of Torque for a technical reviewer. Every claim
below was checked against the code and the test suite at the time of
writing; none is aspirational.

## 1. Problem and scope

Torque is a revenue-leakage recovery agent spanning four funnel legs —
payment degradation, checkout abandonment, subscription/mandate failure, B2B
receivables — unified under one case object and one append-only event
ledger. The build constraint throughout has been **free/self-hosted
infrastructure only** (Postgres, Redis, no paid API, no vector database, no
managed LLM by default).

## 2. Domain model

`RevenueLeakCase` is the single record type shared by every leg. Its
lifecycle is a locked state machine (`torque.state_machine`) with guards
enforced at flush time (`torque.models.guards`) — both files are
byte-unchanged since the very first commit, verified by `git diff` in this
project's own continuation protocol at every module boundary. History is a
single append-only table, `case_event` — a database trigger *and* an
application-level guard both refuse mutation, and no `CaseEvent` type can be
written without a matching validated Pydantic payload schema
(`torque.events.payloads`).

Multi-tenancy is enforced by a single always-injecting data-access layer
(`torque.db.scoped.TenantScope`) — every query in the codebase that touches
tenant-scoped data routes through it; cross-tenant reads return nothing,
cross-tenant writes raise.

## 3. Decisioning pipeline

1. **Ingestion** (`torque.ingestion`) — signature verification before
   parsing, idempotency on the provider's event id, a short self-recovery
   hold (~90s payment / ~30s subscription) before a case is even opened,
   cross-leg case merge, network-wide outage suppression.
2. **Diagnosis** (`torque.diagnosis`) — rule-based root-cause classification
   with a confidence score; below a configured threshold, the case routes to
   a human instead of a playbook.
3. **Policy** (`torque.policy`) — selects and version-pins a bounded playbook
   (a validated step graph: one success edge, ≥1 fallback edge, no cycles).
4. **Execution** (`torque.execution`) — a **Postgres-polling** durable
   execution driver (chosen over Temporal — see §9) that resolves the
   current step, consults the guardrail engine, performs the action, and
   writes the `Action` row and its `CaseEvent` in one transaction
   (`write_action_and_event`) — an action can never exist without its audit
   entry.
5. **Compliance** (`torque.compliance`) — pure predicate functions (no
   enforcement logic of their own) consulted by the execution layer:
   card/UPI/NACH retry budgets, the RBI 24-hour pre-debit notice (with
   self-heal), WhatsApp consent + approved-template gates, quiet hours,
   live-conversation suspension.
6. **Coordination** (`torque.coordination`) — the Outreach Coordinator (a
   4-hour cross-leg quiet period, merged messages instead of duplicate
   contact) and the escalation ceiling that routes exhausted automation to a
   per-merchant human queue.
7. **Reconciliation** (`torque.reconciliation`) — matches an incoming
   payment-success signal back to its leaking case via a matching ladder
   (direct payment-link → indirect amount match with a 24h attribution
   window → merged-set credit re-split → self-paid cancellation), locking
   the case row so two workers can't double-close it.
8. **Scoring** (`torque.scoring`) — `(probability × amount_at_risk) ÷
   expected_next_step_cost`, a cold-start industry-benchmark table warm-started
   by a bounded (0.5×–1.3×) promise-keeping-rate multiplier. One
   implementation, one seam (`priority()`), consumed by both the Outreach
   Coordinator and the human queue — no ranking is ever re-derived by a
   caller.
9. **Reporting** (`torque.reporting`) — descriptive metrics computed on
   demand from the authoritative tables (no persisted aggregate to drift),
   plus a causal/incrementality layer (§6).

## 4. AI layer

`torque.ai` is architecturally isolated: a static test
(`tests/test_ai_boundary.py`) fails the build if it ever imports
`torque.state_machine`, `torque.execution`, or any other write-capable
module. Every AI route is `GET`-only.

Nine phases, each independently complete and tested:

| Phase | Concern | Key property |
|---|---|---|
| 0 | Architectural boundary | Enforced by a static import-scan test, not a convention |
| 1 | Evidence gathering | Read-only, tenant-scoped, redacts PII (`content_sent` never exposed, no `Counterparty` PII fields read) |
| 2 | Citation model | Every evidence item gets a stable `source_type:source_id` id |
| 3 | Precedent retrieval | Postgres full-text search over an exact `(merchant, leg_type, root_cause_code)` filter — no vector DB (unjustified at this corpus size, verified via `EXPLAIN ANALYZE`) |
| 4 | LLM narrative | On-demand only; post-generation citation validation rejects the *entire* narrative if any citation is unresolved; `case_id`/`generated_at`/`provider_id`/`prompt_version` are server-stamped, never provider-trusted |
| 5 | Faithfulness evaluation | A deterministic (no LLM, no embeddings) lexical-overlap proxy for citation support — an explicitly documented v1 limitation, not a semantic-truth claim; test/offline harness, no API |
| 6 | Agent Console integration | One read-only route (`GET /ai/{merchant}/cases/{id}/explain`), surfaced in the canonical Case View |
| 7 | Shadow ML | An observational-only classifier over existing evidence features — no API route, no UI, no effect on any real decision (explicitly out of scope by its own governing task) |
| 8 | Hardening | Provider timeout enforcement (`asyncio.wait_for`), malformed-id guards standardized to the same "not found" error as a real 404, a generic exception-to-500 catch-all, and a citation-context isolation fix (a citation is now validated against the one id-space its context requires, not "any id-space it might match") |

The only concrete `LLMProvider` is `MockProvider` — deterministic, offline,
no API key, no network call — but it is not a hollow stub: it parses the
real evidence payload passed to it and constructs a genuinely
evidence-grounded narrative, so tests asserting "citations resolve against
the supplied evidence" are meaningful rather than tautological. Swapping in
a real network-backed provider touches exactly one function
(`_get_provider()` in `api/ai.py`).

## 5. Explainability

Two independent explanation surfaces, deliberately not merged:

- **The `CaseEvent` audit trail** — deterministic, always present, no AI
  involved. This is the "why did the agent do this" answer for every
  automated decision (diagnosis confidence, guardrail block reason, action
  outcome) and is a query, not a reconstruction.
- **The AI Assessment** — a synthesized, citation-grounded narrative
  *interpretation* of that same evidence, generated only on request, visibly
  distinguished (a gold accent used nowhere else in the UI) so a reviewer
  never mistakes AI interpretation for authoritative state.

## 6. Causal measurement

`torque.reporting.incrementality` computes treatment-vs-control recovery
rates over per-relationship cohort assignments already built into the data
model, with a Wilson score confidence interval per cohort and a
Newcombe-hybrid interval for the lift itself. A documented SUTVA sensitivity
adjustment removes control counterparties who were simultaneously in a
*different* merchant's treatment cohort in the same window (reading only the
counterparty-overlap fact across merchants, never another merchant's
amounts/outcomes/identity), and reports the adjusted lift **alongside**,
never instead of, the headline. The report states explicitly that this is a
point estimate with an honest interval, not proof of causation.

## 7. Frontend

**React 18 + Vite**, source in `frontend/`, built into
`src/torque/ui/static/` and served by the same FastAPI process on the same
port — no Node at runtime, no backend change required to serve it. This is a
migration from an earlier hand-written vanilla JS/CSS SPA, made as a
deliberate, evidence-based decision once the UI's actual component-reuse and
state-management needs (five screens sharing a priority-feed row, a gauge,
an interactive chart, and a citation-anchored AI panel) outgrew what
render-functions-and-`innerHTML` could comfortably sustain; see
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the full decision record, including
the one real regression (a case-switch state bug) the migration surfaced and
fixed. `react-router-dom`'s `HashRouter` preserves the project's original
`#/dashboard`, `#/cases/:id` URL scheme exactly.

A standing test (`tests/test_module10_ui.py`) scans the `frontend/src/`
source tree and fails the build if it ever computes a metric/score/rate
itself (e.g. a literal `probability *` or `* amount_at_risk` substring), or
if any file uses `dangerouslySetInnerHTML` — architecturally enforcing
"render backend data, never recompute it, never bypass the framework's
default escaping."

## 8. Testing

**1436 tests, Postgres-backed**, covering (non-exhaustively): state-machine
legality, guard enforcement, tenant isolation, guardrail predicates end to
end, reconciliation matching/attribution/locking, scoring formula and
warm-start bounds, the AI package boundary, citation validation and
rejection paths, provider timeout/failure-mode handling, evaluation harness
determinism, shadow-ML feature extraction, and static-source assertions
against the shipped frontend JS/CSS/HTML. The suite skips cleanly (with an
explanatory message, not a failure) if no Postgres server is reachable.

## 9. Notable engineering tradeoffs

- **Postgres-polling over Temporal** for durable execution — a real
  alternative was considered and rejected to stay within the free-tier
  infrastructure constraint; the tradeoff is a 10–60s scheduling
  granularity, acceptable at this system's action cadence.
- **No vector database for precedent retrieval** — Postgres full-text search
  over an already-exact metadata filter is sufficient at a dozens-to-low-hundreds
  case corpus; revisit if corpus size changes the calculus.
- **A deterministic lexical-overlap faithfulness proxy instead of an
  LLM-as-judge** — free, local, reproducible, at the cost of missing
  paraphrase-level faithfulness; documented as a v1 limitation rather than
  presented as semantic-truth measurement.
- **No real outbound message/charge delivery** — the execution layer is a
  safe stub; this was a deliberate scope boundary from the start of the
  project, not a shortcut discovered late.

## 10. What is not built

Real outbound delivery (WhatsApp/email/SMS/retry/payment-link creation), a
real (non-mock) LLM provider, per-issuer outage detection (blocked on issuer
data extraction), a persisted/served version of the Phase 5 evaluation
report or the Phase 7 shadow-ML score, and horizontal scaling of the
API/worker processes. None of these are implied as present anywhere in the
UI or this documentation set.
