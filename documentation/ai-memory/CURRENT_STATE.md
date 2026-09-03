# CURRENT STATE — read this first

**Last updated:** 2026-09-03, after the **Module 5 — Execution & Orchestration**
run (uncommitted).
**Reconstructed from:** the committed Module 4 (HEAD `c17dd82`) + the uncommitted
Module-5 run + `Torque_Blueprint_v7_FullSystem.md`.
**This file is derived documentation, not authoritative.** The repo and blueprint win.

---

## What Torque is

A revenue-leakage recovery agent closing the loop across four funnel legs —
**payment degradation, checkout abandonment, subscription/mandate failure, B2B
receivables** — with **one shared case object and one shared event ledger**. It
diagnoses root cause, runs a bounded recovery playbook, executes it under hard
compliance guardrails, and measures incremental recovery against a held-out
control. Full vision: `PROJECT_CONTEXT.md` §1. Spec: `Torque_Blueprint_v7_FullSystem.md`.

## Where we are

**Modules 1–4 — COMPLETE & committed** (`c17dd82`). Signal ingestion → diagnosis
→ policy/playbook selection all live; diagnosed `PLAYBOOK_ACTIVE` cases get a
version-pinned `PlaybookRun` at their entry step.

**Module 5 (Execution & Orchestration) — §5 — COMPLETE** (this run, uncommitted).
`torque.execution` executes a pinned run's graph on the **Postgres-polling** driver
(chosen over Temporal — maintainer decision, D-090, resolves U-07).

| Module 5 capability | Behaviour |
|---|---|
| Driver (§5.6) | `scheduled_job` table (0015) + 10 s/60 s Celery-beat pollers; due rows claimed `FOR UPDATE SKIP LOCKED` |
| Runtime tick | `execute_due_job`: §5.1 loop — guardrails → executor stub → atomic Action+CaseEvent → `STEP_TRANSITIONED` → advance `active_step_id` → reschedule / finalize (all one transaction) |
| Guardrails (§5.2, D-092) | network hard-stop, Card/UPI/NACH budgets, UPI hard-cap + peak-window defer, pre-debit gap w/ auto-insert self-heal, systemic-hold block; quiet-hours/UPI-window are defers |
| Timing (D-025) | offset-from-completion; IST `allowed_hours` deferral (+ overnight); payday `next_month_end_working_day` substitution; never fires early |
| Budgets | Card (`attempts_used_24h/_30d`) + UPI (`attempts_used`) consumed once per fired retry, row-locked; NACH counters are external |
| Executor (§5.4) | internal **stub**, no external I/O — the seam real channel adapters attach to |
| Terminal (D-093) | ESCALATE_HUMAN node → case `ESCALATED_TO_HUMAN`/run `ESCALATED`; else case `EXHAUSTED`/run `COMPLETED` |
| U-02 settled (D-091) | `STEP_TRANSITIONED` = `{run_id, from_step_id, outcome, to_step_id?, edge_condition?}` |

**Modules 6–13 not started.** The Module-5 run is **uncommitted**.

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`c17dd82`** (committed Module 4). Module 5 sits uncommitted on top. |
| Working tree | uncommitted Module-5 run. New: `src/torque/execution/` (`__init__`, `scheduler`, `runner`, `guardrails`, `timing`, `executor`, `rendering`, `tasks`), `src/torque/models/scheduled_job.py`, `migrations/versions/0015_scheduled_job.py`, `tests/test_module5_{timing,execution,guardrails,scheduler,idempotency,multicase,tenancy}.py` (7 files). Modified: `models/__init__.py`, `events/payloads.py` (STEP_TRANSITIONED settled), `ingestion/celery_app.py` (task+beat wiring), `tests/conftest.py` (M5 fixtures). |
| Alembic head / current | **`0015_scheduled_job`** (M5 added it; additive table). |
| Test suite | **808 passed** (`uv run pytest -q`), 0 fail / 0 skip. 1 cosmetic `StarletteDeprecationWarning`. |
| `def test_` functions | **680** |
| Lint | `uv run ruff check .` → clean |
| Migration roundtrip | green (up→down→up incl. 0015) |
| `src/torque/state_machine.py` | **byte-unchanged vs HEAD**. M5 uses the existing `PLAYBOOK_ACTIVE → {ESCALATED_TO_HUMAN, EXHAUSTED}` edges. |
| `src/torque/models/guards.py` | **byte-unchanged vs HEAD**. |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI, **Celery + Redis + beat** (now also the execution pollers), PostgreSQL 16, `uv`, pytest, ruff |
| DB / infra | Postgres host **5442**; Redis host **6389**. Tests run eager/mocked. **24 tables** (M5 added `scheduled_job`). |

## What is implemented (new in Module 5)

- **`torque.execution`** package: `scheduler.py` (schedule/claim/poll), `runner.py`
  (`execute_due_job`, the §5.1 tick), `guardrails.py` (§5.2 Module-5 half),
  `timing.py` (D-025 fire-time), `executor.py` (§5.4 stub), `rendering.py` (§4.4
  multi-case), `tasks.py` (two beat pollers).
- **`scheduled_job`** model + migration 0015. **`STEP_TRANSITIONED`** payload
  settled in `events/payloads.py` (D-091). `celery_app` registers the pollers.

Full breakdown: `ARCHITECTURE.md` §8E.

## Next milestone

**Module 6 — Compliance & Cross-Leg Guardrail Engine.** The canonical
`GuardrailEngine.check()` facade (the callable home Module 5 consults), the
Outreach Coordinator (Part A §5 — priority, 4 h cross-leg quiet period, merge,
defer, open-conversation policy), the WhatsApp consent + approved-template gate,
escalation-ceiling → `ESCALATED_TO_HUMAN` (§6.3), and the human queue. Module 5
left these as the confirmed Module 5/6 line (D-092). Do not start without an
approved scope.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`.
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** (Module 5 resolved
   U-07 and U-02 — both on explicit authority: U-07 by the maintainer's engine
   choice, U-02 by Module 5's mandate to settle it.)
6. `state_machine.py` / `guards.py` are load-bearing. Changing either needs
   explicit approval + a shown diff. (Module 5 changed **neither**.)
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01** — edges 1–2 (`DETECTED/DIAGNOSING → CANCELLED`) — Module 7. Edge 3
  RESOLVED (M7c). `DIAGNOSING → SYSTEMIC_HOLD` residual: not needed by M3–M5.
- **U-02** — **RESOLVED** (Module 5, D-091): `STEP_TRANSITIONED` shape settled.
- **U-03** — Tier 1 vs Tier 3 MAC precedence is a stated default. Open.
- **U-04** — systemic N / M / sustain numbers are placeholders. Open.
- **U-07** — **RESOLVED** (Module 5, D-090): durable execution = Postgres-polling.
- **U-08** — issuer / BIN / acquirer / route extraction; blocks `ISSUER_SPECIFIC`
  systemic detection, the §5.3 first-touch MAC lookup (D-083), and MAC self-healing.
- **U-05 / U-06** — Part D items 1–4; `MacCodeRegistry` unseeded codes.

## Known contradictions / caveats

- **`README.md` is stale.** Trust `CURRENT_STATE.md` / the code.
- **The Module-5 run is uncommitted.** Every "verified fact" above (808 tests, the
  `torque.execution` package, migration 0015) reflects the working tree.
- **Execution is not auto-triggered.** No auto-dispatch anywhere: Module 2→3
  (D-080), 3→4 (D-088), **4→5** (D-093). Each engine + task is ready and invocable;
  the demo/tests wire them explicitly (`activate_case` → `schedule_run` → pollers).
- **The executor is a stub (§5.4).** `run_action` performs no external I/O and
  returns `SUCCESS` by default; real WhatsApp/email/SMS/retry/Payment-Link adapters
  are deferred. So Module 5 fires no real messages or charges — safe by construction.
- **Module 5/6 line (D-092):** Module 5 enforces retry-rail + systemic + timing
  guardrails; the `GuardrailEngine` facade, Outreach Coordinator, and WhatsApp
  consent/template gate are **Module 6**. Systemic hold is a §5.2 **BLOCK**
  (follows `on_blocked`), not an invented state transition.
- **Recovery closure stays Module 7.** A successful retry (stub) advances the graph;
  it does **not** mark the case `RECOVERED` (that's Module 7 reconciliation,
  out-of-band). A drained ladder ends `EXHAUSTED` or `ESCALATED_TO_HUMAN`.
- **`NETWORK_HARD_STOP`** is the `BlockReason` used for both TIER_1 and TIER_3 retry
  blocks (the enum has no instrument-dead value; §5.2.1's
  `INSTRUMENT_NOT_RECURRING_CAPABLE` is a `HardStopReason`).
- Module 1–4 caveats still stand.

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py src/torque/models/guards.py`), report
any drift, then — once the maintainer has committed Module 5 — propose **Module 6 —
Compliance & Cross-Leg Guardrail Engine** as one continuous scope.
