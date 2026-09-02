# CURRENT STATE — read this first

**Last updated:** 2026-09-02, after Milestone 7c (uncommitted — maintainer
commits the whole Milestone 7 tree).
**Reconstructed from:** repo commit `47cf6d7` (M6b) + working-tree M7a + M7b +
M7c + `Torque_Blueprint_v7_FullSystem.md`.
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

**Module 2 (Signal Ingestion) — blueprint Part B — in progress:**
- **M7a:** `POST /webhooks/razorpay/{merchant_id}` + `GET /health`,
  verify-before-parse, `Event` write + idempotency.
- **M7b:** Leg-1 path — Celery + Redis (broker only) self-recovery buffer (§2.3,
  `payment.failed`, 90s), cross-leg dedup / Merge (§2.4, live direction only),
  `payment.failed → PAYMENT_DEGRADATION` case creation in `DETECTED`,
  counterparty resolution, `CardRetryBudget` seeding.
- **M7c:** §2.5 **`NETWORK_WIDE` systemic detection** — a 60s **Celery beat**
  job (`torque.ingestion.systemic`): per-merchant trailing-10-min failures/min
  vs. a trailing-7-day baseline (excludes the live window), the existing
  `systemic_threshold_breached` predicate, `SystemicEvent(NETWORK_WIDE)`
  creation, sweep of open `DETECTED` cases → `SYSTEMIC_HOLD` (+ `STATUS_CHANGED`
  + `SYSTEMIC_HOLD_APPLIED`), resolution via `systemic_resolved` → `resolved_at`
  + batch `SYSTEMIC_HOLD → DIAGNOSING` (FK left set), and the §2.7 ingestion
  hook (a case created during an active event is born held). **Plus one approved
  state-machine edge**: `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` (U-01 #3, D-066) —
  legal but **dormant** (no M7c code drives it).

**Modules 3–13 not started.** Not built in Module 2 yet: `ISSUER_SPECIFIC`
detection (blocked — U-08); Leg 2/3/4 ingestion; the `subscription.charged.failed`
30s buffer; the reverse Merge direction; `UPIRetryBudget` seeding (Leg 3);
dispatch to Module 3; driving the `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` edge (Module 5).

Milestones delivered: **M1–M6b** (committed) + **M7a**, **M7b**, **M7c**
(complete + verified, **uncommitted**). See `MILESTONES.md`.

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | `47cf6d7` "Milestone 6b: …" — **7 commits; M7a/M7b/M7c are NOT committed** |
| Working tree | M7a + M7b + M7c, uncommitted. Modified (tracked): `pyproject.toml`, `docker-compose.yml`, `src/torque/config.py`, `src/torque/models/event.py`, `src/torque/contexts/payment_degradation.py`, **`src/torque/state_machine.py`** (M7c — the one approved edge + docstring), `tests/conftest.py`, `tests/test_schema_introspection.py`, `tests/test_state_machine.py`. New (untracked): `src/torque/api/` (M7a), `src/torque/ingestion/` (M7b + M7c `systemic.py`), `src/torque/__main__.py`, `migrations/versions/0013_event_ingestion_index.py`, `tests/test_webhook_ingestion.py` + `tests/test_ingestion_*.py` + `tests/test_cross_leg_dedup.py` + `tests/test_webhook_dispatch.py` + `tests/test_systemic_detection.py`. Also untracked (maintainer's): `documentation/`, `uv.lock`. |
| Alembic head / current | `0013_event_ingestion_index` (M7a). **M7b and M7c added no migration.** |
| Test suite | **519 passed** (`uv run pytest -q`), 0 fail / 0 skip with DB up. 1 cosmetic `StarletteDeprecationWarning`. |
| `def test_` functions | **460** (519 collected with parametrize) |
| Lint | `uv run ruff check .` → clean |
| Migration roundtrip | green (up→down→up) |
| `src/torque/state_machine.py` | **changed in M7c — exactly** `+CaseStatus.SYSTEMIC_HOLD` in `_TRANSITIONS[PLAYBOOK_ACTIVE]` + the docstring "NOT YET ADDED" cleanup. Nothing else. (Byte-stable M1→M7b.) |
| `src/torque/models/guards.py` | **unchanged since M6a** — `git diff HEAD` empty. M7a/M7b/M7c did not touch it. |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI + uvicorn (M7a), **Celery + Redis broker + Celery beat (M7b/M7c)**, PostgreSQL 16, `uv`, pytest, ruff, httpx (dev) |
| DB / infra (docker-compose) | Postgres host **5442**; Redis host **6389** (Celery broker). A real worker + beat need Redis up; tests run eager/mocked and don't. |

## What is implemented

**23 ORM models / 23 tables** — unchanged since M6b (M7a/M7b/M7c added no table).

Module 1 supporting logic: `TenantScope`, `torque.models.guards`,
`torque.state_machine` (+ the M7c edge), `torque.contexts`, `torque.events`,
`torque.playbooks`, `torque.compliance`, `torque.promises`,
`torque.security.razorpay_signature`, `torque.config`.

**`torque.api`** (M7a): `create_app()`; `GET /health`; `POST
/webhooks/razorpay/{merchant_id}`.

**`torque.ingestion`** (M7b + M7c):
- M7b: `celery_app` (Redis broker), `tasks.resolve_buffered_event_task`,
  `buffer`, `cases.create_or_attach_case`, `dedup`, `identity`, `payloads`,
  `outcomes.BufferOutcome`.
- M7c: `celery_app.conf.beat_schedule` (`systemic-detection`, 60s);
  `tasks.detect_systemic_task`; **`systemic.py`** —
  `run_systemic_detection` / `_detect_and_hold` / `_check_and_resolve` /
  `_hold_case` / `_active_network_wide_event` / `apply_active_hold_if_any` (the
  §2.7 hook, called by `cases.create_or_attach_case`) / `_failure_count` /
  `_baseline_failure_rate`.

`PolicyConfig` (M7c): `systemic_detection_window_minutes = 10`,
`systemic_baseline_days = 7` (both blueprint figures). N / M / sustain stay
**U-04 placeholders** — M7c consumes, does not validate/tune them.

Full tagged breakdown: `ARCHITECTURE.md` §8A (HTTP) and §8B (ingestion + systemic).

## Next likely milestone

**Leg 3 ingestion.** `subscription.charged.failed` → `SUBSCRIPTION_FAILURE`
case: the 30s self-recovery buffer, `SubscriptionFailureContext` (all four
fields, Razorpay method → `mandate_type` mapping), and **`UPIRetryBudget`
seeding** (per-mandate, from this producer — D-069) / `NACHRetryPolicy` seeding.

Then: **Leg 4** (`invoice.overdue` / `B2BInvoice` bundling); **Leg 2**
(`checkout.abandoned` synthetic-injection endpoint + the **reverse cross-leg
Merge**); **`ISSUER_SPECIFIC` systemic detection** (needs issuer extraction —
U-08). Propose each as its own written scope; do not start without approval.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** Read-only git only. The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`.
3. **One milestone at a time.** Inspect → propose → lock → implement approved
   scope only → verify → report → STOP.
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally** — surface them.
6. `state_machine.py` / `guards.py` are load-bearing. Changing either needs
   explicit approval + a shown diff. (M7c changed `state_machine.py` by exactly
   one approved edge; `guards.py` remains untouched.)
7. Every verification run: `pytest`, `ruff check .`, migration up/down/up
   roundtrip, `git diff HEAD` of `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01** — edges 1–2 (`DETECTED→CANCELLED`, `DIAGNOSING→CANCELLED`) still not
  in `state_machine.py` — Module 7. **Edge 3 (`PLAYBOOK_ACTIVE→SYSTEMIC_HOLD`)
  RESOLVED in M7c** (D-066). `DIAGNOSING→SYSTEMIC_HOLD` is a residual not tracked
  as an edge — needs its own proposal if Module 3 needs it.
- **U-04** — systemic N / M / sustain numbers are placeholders. **M7c consumes
  them; did not validate or tune them.** Still open.
- **U-07** — inbound half RESOLVED (Celery + Redis). `PlaybookRun`-execution
  half (Temporal vs Postgres-polling) stays open — Module 5.
- **U-08 (new, M7c)** — issuer / BIN / acquirer / route extraction: which field,
  from where, on which model, which milestone. Blocks `ISSUER_SPECIFIC` systemic
  detection.
- **U-02** — `CaseEvent.STEP_TRANSITIONED` payload shape provisional (Module 5).
- **U-03** — Tier 1 vs Tier 3 MAC precedence is a stated default.
- **U-05 / U-06** — blueprint Part D items 1–4; `MacCodeRegistry` unseeded codes.

## Known contradictions / caveats

- **`README.md` is stale.** Says "Milestone 1 (partial)", "migrations 0001 →
  0005", "not yet under git". All false. Trust `CURRENT_STATE.md` / the code.
- **M7a + M7b + M7c are uncommitted.** `git log` shows 7 commits ending at
  `47cf6d7`. Every "verified fact" above (519 tests, migration `0013`, the
  `api/` + `ingestion/` packages, the state-machine edge) reflects the working
  tree, not any commit.
- **Systemic detection is `NETWORK_WIDE` only.** `ISSUER_SPECIFIC` is NOT built
  (U-08). Do not report §2.5 as fully done.
- **`PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` is legal but dormant** — no code path drives
  it; Module 5 owns that. The M7c job sweeps `DETECTED` cases only.
- **`UPIRetryBudget` seeding is NOT done** — it is a Leg-3 requirement (D-069).
  **Leg 2/3/4 ingestion and the reverse Merge are NOT done.**
- **`CardRetryBudget.card_token_hash` holds the raw Razorpay token ref** (M7b,
  D-061) — no PAN, no hashing; hardening deferred.
- **`ARCHITECTURE.md` §2** "`len(Base.metadata.tables) == 23`" — `Base` imports
  from `torque.db.base`, not `torque.models`. Cosmetic.

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py src/torque/models/guards.py`),
report any drift, then — once the maintainer has committed the Milestone 7 tree —
propose **Leg 3 ingestion** as a written scope with every ambiguity numbered
(Razorpay method → `mandate_type` mapping, `UPIRetryBudget` seeding key, 30s
buffer semantics), and wait for approval before writing code.
