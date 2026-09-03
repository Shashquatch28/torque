# CURRENT STATE — read this first

**Last updated:** 2026-09-03, after the **Module 3 — Diagnosis Engine** run
(uncommitted).
**Reconstructed from:** commit `c71c90e` ("Additional Commit" — committed Module 2)
+ the uncommitted Module-3 run + `Torque_Blueprint_v7_FullSystem.md`.
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

**Module 2 (Signal Ingestion) — blueprint Part B — COMPLETE** and **committed**
(`c71c90e`). All four signal legs ingest reliably, idempotently, causality-aware
into canonical `RevenueLeakCase`s in `DETECTED`; bidirectional §2.4 Merge; §2.5
`NETWORK_WIDE` systemic detection + hold/resume.

**Module 3 (Diagnosis Engine) — blueprint §3 — COMPLETE** (this run, uncommitted).
The `torque.diagnosis` package converts a `DETECTED` (or §2.5-resumed `DIAGNOSING`)
case into a `root_cause_code` + `diagnosis_confidence` and routes it by `T = 0.65`.

| Aspect | Module 3 behaviour |
|---|---|
| Vocabulary | `RootCauseCode` (Module-3-owned §3.1 StrEnum, 23 members; `.value` → plain `String` column) |
| Payment/Subscription | TIER_1/TIER_3 `network_directive` precedence (0.95) → decline-code lookup (known 0.75 / opaque 0.4) → missing-code gateway-timeout (0.5); subscription adds §3.2.4 mandate **facts** first (1.0) and reads decline from source Event |
| Checkout | `(drop_stage, payment_method_attempted)` → every band < T ⇒ always escalates |
| B2B | `days_overdue × promise_keeping_rate`; established (≥3 invoices) 0.8 / cold-start 0.4 |
| `is_hard_decline` | set here (PAYMENT_DEGRADATION only, derived from root cause, D-058/D-084) |
| `suggested_timing_adjustment` | §3.4 payday hint → new case column (migration 0014) |
| Routing | `< T` → `ESCALATED_TO_HUMAN`; `≥ T` → `PLAYBOOK_ACTIVE`; one `DIAGNOSIS_COMPLETED` event; all atomic, idempotent, tenant-scoped |

**Modules 4–13 not started.** HEAD is `c71c90e`; the Module-3 run is **uncommitted**.

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`c71c90e`** "Additional Commit" (the committed Module 2) |
| Working tree | uncommitted Module-3 run. New: `src/torque/diagnosis/` (`__init__`, `root_causes`, `decline_codes`, `classifier`, `engine`, `tasks`), `migrations/versions/0014_diagnosis_timing.py`, `tests/test_diagnosis_{engine,classifier,idempotency,routing,atomicity,tenancy,task}.py`. Modified: `src/torque/models/revenue_leak_case.py` (+1 col), `src/torque/ingestion/celery_app.py` (task registration). |
| Alembic head / current | **`0014_diagnosis_timing`** (M3 added it). Additive: one nullable `revenue_leak_case.suggested_timing_adjustment VARCHAR(64)`. |
| Test suite | **687 passed** (`uv run pytest -q`), 0 fail / 0 skip with DB up. 1 cosmetic `StarletteDeprecationWarning`. |
| `def test_` functions | **585** |
| Lint | `uv run ruff check .` → clean |
| Migration roundtrip | green (up→down→up), incl. 0014 |
| `src/torque/state_machine.py` | **byte-unchanged vs HEAD** (`git diff HEAD` empty). M3 uses the existing `DETECTED→DIAGNOSING→{PLAYBOOK_ACTIVE,ESCALATED_TO_HUMAN}` edges. |
| `src/torque/models/guards.py` | **byte-unchanged vs HEAD** (`git diff HEAD` empty). |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI + uvicorn, **Celery + Redis broker + Celery beat**, PostgreSQL 16, `uv`, pytest, ruff, httpx (dev) |
| DB / infra | Postgres host **5442**; Redis host **6389** (Celery broker). Tests run eager/mocked. |

## What is implemented (new in Module 3)

- **`torque.diagnosis`** package: `root_causes.py` (`RootCauseCode`, `VALID_BY_LEG`,
  `is_hard_decline_for`, `timing_hint_for`, `LABELS`), `decline_codes.py`
  (`DeclineCategory` + `categorise`, demo-scope seed), `classifier.py` (pure per-leg
  rules → `DiagnosisResult`), `engine.py` (`diagnose_case` + `DiagnosisOutcome`:
  eligibility, tenant-scoped I/O, one atomic block, confidence routing), `tasks.py`
  (`diagnose_case_task`).
- **`RevenueLeakCase.suggested_timing_adjustment`** column (0014).
- **`celery_app`** now registers `torque.diagnosis` tasks (2-line additive change).

23 ORM models / 23 tables unchanged (only a column added). Full breakdown:
`ARCHITECTURE.md` §8C (diagnosis).

## Next milestone

**Module 4 — Policy & Playbook Engine.** Root cause → bounded, branching action
graph; the playbook catalog (one `Playbook` per non-trivial `root_cause_code`);
reads `suggested_timing_adjustment` (§4.3 payday application); consumes the
`PLAYBOOK_ACTIVE` cases Module 3 routes. Note: Module 4's *save-time validation*
(`steps_graph` / `stopping_rules`) was already built in M4/M6 — what remains is the
catalog + selection + `PlaybookRun` instantiation. Do not start without an approved
scope.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** Read-only git only. The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`.
3. **One module = one implementation run = one audit** (current workflow).
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** Routine data-mapping
   choices may be made and documented as decisions.
6. `state_machine.py` / `guards.py` are load-bearing. Changing either needs
   explicit approval + a shown diff. (Module 3 changed **neither**.)
7. Every verification run: `pytest`, `ruff check .`, migration up/down/up
   roundtrip, `git diff HEAD` of `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01** — edges 1–2 (`DETECTED→CANCELLED`, `DIAGNOSING→CANCELLED`) — Module 7.
  Edge 3 RESOLVED (M7c). `DIAGNOSING→SYSTEMIC_HOLD` residual: Module 3 did **not**
  need it (diagnosis holds `DIAGNOSING` only transiently inside one transaction).
- **U-04** — systemic N / M / sustain numbers are placeholders. Open.
- **U-07** — inbound half RESOLVED (Celery + Redis). `PlaybookRun`-execution half
  stays open — Module 5.
- **U-08** — issuer / BIN / acquirer / route extraction; blocks `ISSUER_SPECIFIC`
  systemic detection **and** (new) the §5.3 first-touch MAC lookup at diagnosis
  time (D-083).
- **U-02** — `CaseEvent.STEP_TRANSITIONED` payload shape provisional (Module 5).
- **U-03** — Tier 1 vs Tier 3 MAC precedence is a stated default.
- **U-05 / U-06** — blueprint Part D items 1–4; `MacCodeRegistry` unseeded codes.

## Known contradictions / caveats

- **`README.md` is stale.** Trust `CURRENT_STATE.md` / the code.
- **The Module-3 run is uncommitted.** `git log` ends at `c71c90e` (committed
  Module 2). Every "verified fact" above (687 tests, the `torque.diagnosis`
  package, migration 0014) reflects the working tree, not any commit.
- **No auto-dispatch Module 2 → Module 3** (D-080). The diagnosis engine + task are
  ready and independently invocable, but no ingestion leg enqueues them — the
  cross-module trigger is deferred to the orchestration layer. Cases produced by
  ingestion still sit in `DETECTED`.
- **Module 3 consumes `network_directive_tier` but extracts no MAC code** (D-083) —
  no MAC/issuer code is surfaced for it (U-08). Diagnosis uses the decline-code path.
- **Subscription decline codes come from the source `Event`** (`payment.entity.error_code`),
  not the typed context, which stores only mandate identity (D-081).
- **Checkout cases always escalate** — every checkout confidence band is < T by
  construction (§3.2 "honestly low"). B2B cold-start (0.4) escalates; established
  (0.8) routes to playbook.
- **`PLAYBOOK_ACTIVE → SYSTEMIC_HOLD`** legal but dormant (Module 5 owns driving it).
- Module-2 caveats still stand (Leg-3 rail seeding initial-state only D-072; systemic
  rollup `payment.failed`-only D-073; `NETWORK_WIDE`-only U-08; `card_token_hash`
  holds the raw token ref D-061; etc.).

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py src/torque/models/guards.py`), report
any drift, then — once the maintainer has committed Module 3 — propose **Module 4 —
Policy & Playbook Engine** as one continuous scope per the module execution protocol.
