# CURRENT STATE — read this first

**Last updated:** 2026-09-03, after the **Module 2 completion run** (uncommitted).
**Reconstructed from:** commit `2a35786` (Milestone 7) + uncommitted M8 (Leg 3)
+ uncommitted Module-2 completion run (Legs 2 & 4 + bidirectional Merge) +
`Torque_Blueprint_v7_FullSystem.md`.
**This file is derived documentation, not authoritative.** The repo and blueprint win.

---

## What Torque is

A revenue-leakage recovery agent. It closes the leakage loop across four funnel
legs — **payment degradation, checkout abandonment, subscription/mandate failure,
B2B receivables** — with **one shared case object and one shared event ledger**.
It diagnoses root cause, runs a bounded recovery playbook, executes it under hard
compliance guardrails, and measures incremental recovery against a held-out
control. Full vision: `PROJECT_CONTEXT.md` §1. Spec: `Torque_Blueprint_v7_FullSystem.md`.

## Where we are

**Module 1 (Core Data Model) — blueprint Part A — COMPLETE** (M1–M6b).

**Module 2 (Signal Ingestion) — blueprint Part B — COMPLETE.** All four signal
legs ingest reliably, idempotently, and causality-aware into canonical
`RevenueLeakCase`s via one shared engine; the §2.4 cross-leg Merge is
bidirectional; §2.5 `NETWORK_WIDE` systemic detection + hold/resume are live.

| Leg | Signal | Buffer | Case | Extras |
|---|---|---|---|---|
| 1 | `payment.failed` | 90 s | `PAYMENT_DEGRADATION` | `CardRetryBudget` seed; forward Merge |
| 2 | `checkout.abandoned` (signed `/internal` injection) | none | `CHECKOUT_ABANDONMENT` | reverse Merge |
| 3 | `subscription.charged.failed` | 30 s | `SUBSCRIPTION_FAILURE` | UPI/NACH/Card rail seed |
| 4 | `invoice.overdue` | none | `B2B_RECEIVABLE` | `B2BInvoice` + §3 grouping; Σ outstanding |

All legs: verify-before-parse → `Event` → (buffer where required) → idempotency
→ counterparty + `Merchant_Counterparty` resolution → case create/attach in
`DETECTED` → §2.7 systemic hold-on-ingest → `Event.processed = True`, all in one
`session_scope()` transaction. Success signals (`payment.captured`,
`subscription.charged`) are persisted only.

**Modules 3–13 not started.** HEAD is `2a35786` (Milestone 7); M8 and the
Module-2 completion run are **uncommitted**.

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`2a35786`** "Milestone 7: Signal ingestion — webhook, recovery buffer, dedup, case creation, systemic hold" (8 commits) |
| Working tree | uncommitted: M8 + the Module-2 completion run. New: `src/torque/api/checkout_injection.py`, `src/torque/ingestion/{checkout,b2b,subscription}.py`, `tests/test_{checkout_injection,checkout_case_creation,cross_leg_dedup_reverse,b2b_ingestion,module2_integrity,subscription_*}.py`. Modified: `src/torque/api/{app,webhooks}.py`, `src/torque/ingestion/{payloads,dedup,tasks,cases,outcomes}.py`, `src/torque/config.py`, `tests/conftest.py`, `tests/test_{schema_introspection,ingestion_atomicity}.py`. |
| Alembic head / current | `0013_event_ingestion_index`. **No migration in M8 or the completion run.** |
| Test suite | **601 passed** (`uv run pytest -q`), 0 fail / 0 skip with DB up. 1 cosmetic `StarletteDeprecationWarning`. |
| `def test_` functions | **537** |
| Lint | `uv run ruff check .` → clean |
| Migration roundtrip | green (up→down→up) |
| `src/torque/state_machine.py` | **byte-unchanged vs HEAD** (`git diff HEAD` empty). Contains the M7c `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` dormant edge (committed in `2a35786`). |
| `src/torque/models/guards.py` | **byte-unchanged vs HEAD** (`git diff HEAD` empty). |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI + uvicorn, **Celery + Redis broker + Celery beat**, PostgreSQL 16, `uv`, pytest, ruff, httpx (dev) |
| DB / infra | Postgres host **5442**; Redis host **6389** (Celery broker). Real worker + beat need Redis up; tests run eager/mocked. |

## What is implemented

**23 ORM models / 23 tables** — unchanged since M6b. Module 2 writes existing
ones only (`event`, `revenue_leak_case`, `counterparty`, `merchant_counterparty`,
`card_retry_budget`, `upi_retry_budget`, `nach_retry_policy`, `b2b_invoice`).

- **`torque.api`**: `create_app()`; `GET /health`; `POST
  /webhooks/razorpay/{merchant_id}` (Legs 1/3/4 + success signals); `POST
  /internal/checkout-abandoned/{merchant_id}` (Leg 2 signed injection, D-074).
- **`torque.ingestion`**: `buffer.py`/`cases.py` (Leg 1), `subscription.py`
  (Leg 3), `checkout.py` (Leg 2), `b2b.py` (Leg 4), `dedup.py` (bidirectional
  §2.4 — `find_supersedable_case` + `find_supersedable_payment_case`),
  `systemic.py` (§2.5 `NETWORK_WIDE` + the `apply_active_hold_if_any` §2.7 hook),
  `identity.py`, `payloads.py` (payment/subscription/invoice/checkout
  extractors), `outcomes.BufferOutcome` (`NOOP`/`SELF_RECOVERED`/`CASE_CREATED`/
  `CASE_MERGED`/`CASE_ATTACHED`), `celery_app.py` (broker + beat), `tasks.py`
  (one task per leg + `detect_systemic_task`).
- `PolicyConfig`: `checkout_injection_secret` (D-074). Systemic N/M/windows
  unchanged (U-04 placeholders).

Full tagged breakdown: `ARCHITECTURE.md` §8A (HTTP) and §8B (ingestion).

## Next milestone

**Module 3 — Diagnosis Engine.** Root-cause classification + confidence bands;
introduces the `root_cause_code` enum (Module 3 owns it — deliberately NOT in
`enums.py` today); per-leg rule-based classification; `DIAGNOSING →
PLAYBOOK_ACTIVE` vs `DIAGNOSING → ESCALATED_TO_HUMAN` routing on
`PolicyConfig.diagnosis_confidence_threshold` (0.65); writes `DIAGNOSIS_COMPLETED`
`CaseEvent`s. It consumes the `DETECTED` cases Module 2 produces. Do not start
without an approved scope.

Deferred Module-2 refinements (do **not** block Module 3): `ISSUER_SPECIFIC`
systemic detection (U-08); systemic rollup over `subscription.charged.failed`
(D-073); a real storefront pixel for Leg 2 (Part D item 1); a `docker-compose`
worker/beat service.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** Read-only git only. The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`. (E.g. an instruction claimed
   `CASE_SUPERSEDED` was "authoritative" — it is not; the blueprint §4 CaseEvent
   table is closed at 10 (D-007). The maintainer confirmed no new type — D-076.)
3. **One unit at a time** — now module-by-module (one module = one implementation
   run = one audit); no sub-phase approvals.
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** Routine
   data-mapping choices may be made and documented as decisions.
6. `state_machine.py` / `guards.py` are load-bearing. Changing either needs
   explicit approval + a shown diff.
7. Every verification run: `pytest`, `ruff check .`, migration up/down/up
   roundtrip, `git diff HEAD` of `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01** — edges 1–2 (`DETECTED→CANCELLED`, `DIAGNOSING→CANCELLED`) — Module 7.
  Edge 3 RESOLVED (M7c). `DIAGNOSING→SYSTEMIC_HOLD` residual — its own proposal
  if Module 3 needs it.
- **U-04** — systemic N / M / sustain numbers are placeholders; consumed, not
  validated/tuned. Still open.
- **U-07** — inbound half RESOLVED (Celery + Redis). `PlaybookRun`-execution
  half stays open — Module 5.
- **U-08** — issuer / BIN / acquirer / route extraction; blocks `ISSUER_SPECIFIC`
  systemic detection.
- **U-02** — `CaseEvent.STEP_TRANSITIONED` payload shape provisional (Module 5).
- **U-03** — Tier 1 vs Tier 3 MAC precedence is a stated default.
- **U-05 / U-06** — blueprint Part D items 1–4; `MacCodeRegistry` unseeded codes.

## Known contradictions / caveats

- **`README.md` is stale.** Trust `CURRENT_STATE.md` / the code.
- **M8 + the Module-2 completion run are uncommitted.** `git log` ends at
  `2a35786`. Every "verified fact" above (601 tests, `checkout.py`/`b2b.py`, the
  `/internal` route) reflects the working tree, not any commit.
- **Systemic detection is `NETWORK_WIDE` only** (U-08) and its rollup counts only
  `Event(type="payment.failed")` — not subscription failures (D-073). The §2.7
  hold-on-ingest hook *does* apply to canonical Leg-2/Leg-4 cases (D-078).
- **`PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` is legal but dormant** — no code drives it;
  Module 5 owns that.
- **Leg 3 rail seeding is initial-state only** — per-decline increments,
  `UPIRetryBudget.mandate_cancelled_at`, and the real NPCI NACH
  `return_reason_code` / `retry_eligible_after` are Module 5 (D-072).
- **`CardRetryBudget.card_token_hash` holds the raw Razorpay token ref** (D-061)
  — no PAN, no hashing.
- **Leg-2 `mandate_id` never uses `subscription.id`** (`payment.entity.token_id`
  only, D-072).
- **`B2BInvoice`**: ingestion creates the invoice + case and maintains
  `amount_at_risk` = Σ outstanding; `outstanding_amount` decrement on payment,
  dunning, and case closure are Modules 4–7.
- **`ARCHITECTURE.md` §2** "`len(Base.metadata.tables) == 23`" — `Base` imports
  from `torque.db.base`, not `torque.models`. Cosmetic.

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py src/torque/models/guards.py`),
report any drift, then — once the maintainer has committed Module 2 — propose
**Module 3 — Diagnosis Engine** as one continuous scope per the project execution
protocol.
