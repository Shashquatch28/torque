# CURRENT STATE — read this first

**Last updated:** 2026-09-04, after the **Module 8 — Recovery Scoring Model** run
(uncommitted, on top of committed Module 7 `dd995d2`).
**Reconstructed from:** committed Modules 1–7 (HEAD `dd995d2`) + the uncommitted
Module 8 changes + `Torque_Blueprint_v7_FullSystem.md`.
**This file is derived documentation, not authoritative.** The repo and blueprint win.

---

## What Torque is

A revenue-leakage recovery agent closing the loop across four funnel legs —
**payment degradation, checkout abandonment, subscription/mandate failure, B2B
receivables** — with **one shared case object and one shared event ledger**. It
diagnoses root cause, runs a bounded recovery playbook, executes it under hard
compliance guardrails, reconciles incoming payments back to the case that was
leaking, and — new in Module 8 — **scores every open case by its economic
recovery opportunity** so scarce outreach and human attention chase
`(probability × amount_at_risk) ÷ cost`, not every case equally. Full vision:
`PROJECT_CONTEXT.md` §1. Spec: `Torque_Blueprint_v7_FullSystem.md`. Product-pitch
knowledge base: `learning_log.md` (root).

## Where we are

**Modules 1–7 — COMPLETE & committed** (`dd995d2`). Signal ingestion → diagnosis
→ policy/playbook → execution → compliance/guardrail engine + Outreach
Coordinator + human queue → payment reconciliation & attribution all live.

**Module 8 (Recovery Scoring Model) — §8 — COMPLETE** (this run, **uncommitted**).
New package `torque.scoring`; migration `0017_recovery_score`.

| Module 8 capability | Behaviour |
|---|---|
| Cold-start probability (§8.1) | `torque.scoring.benchmarks.cold_start_probability(leg_type, days_since_failure, *, amount_at_risk=None)` — Decision F's exact 8-value table as a live function. SUBSCRIPTION `hours ≤ 48` → 0.65 / `days ≤ 7` → 0.45 / else 0.25; PAYMENT DEGRADATION → 0.55; CHECKOUT → 0.40; B2B `days ≤ 30` → 0.35 / `≤ 90` → 0.20 / else 0.12. Bucket boundaries explicit + tested; the 48h–72h label gap folds into the aging bucket. `amount_bucket` is in the signature but **inert** (Decision F seeds no amount tiers — D-110). |
| Warm-start (§8.2) | `warm_start_multiplier(rate)` = `0.5 + rate·0.8`, clamped to `[warm_start_cap_low, warm_start_cap_high]` (0.5 / 1.3). `None` history → ×1.0; `rate 0.0` → ×0.5 (lower cap); `rate 1.0` → ×1.3 (upper cap); `≈0.625` → ×1.0. `adjusted_probability` clamps the product to `[0, 1]` (D-110). |
| Cost (§8.2) | `torque.scoring.cost.compute_cost(session, case)` — Σ `ChannelRateCard.rate_per_unit` for the **next likely step**'s channel(s): the node at a live `PlaybookRun.active_step_id`, else the candidate playbook's entry node (`select_playbook_id`), else none. Zero / `payment_link` / missing-row / no-step → `effective_cost` floors at `PolicyConfig.recovery_score_cost_floor` (₹0.01); `cost_basis` + `next_step_source` record why (D-111). No division by zero possible. |
| Score (§8.4 / §8.7) | `compute_recovery_score(session, case, *, now=None)` → `RecoveryScore` — the **one** implementation of `(probability × amount_at_risk) ÷ cost`, exact `Decimal`, 4 dp. `.explain()` = the "Why:" shape; `.to_dict()` = the JSONB breakdown. Negative `amount_at_risk` → `RecoveryScoreError`; `None` → 0. |
| Persistence (D-109) | Migration **0017** — `revenue_leak_case.recovery_score` `NUMERIC(18,4)`, `recovery_score_breakdown` `JSONB`, `recovery_score_updated_at` `TIMESTAMPTZ`. A **derived cache** — no guard, no `CaseEvent`, no status change. |
| Recompute (§8.5) | `score_case(session, case)` called inline at the end of every leg's ingestion path (`ingestion.{cases,checkout,subscription,b2b}`) and `diagnosis.engine._apply_result`; `recompute_open_cases` (daily) re-scores every open non-superseded case and refreshes any `human_queue` entry's `priority`. Daily via one `beat_schedule` entry (`crontab(hour=2, minute=0)`). Terminal / superseded cases never scored (D-112). |
| Module 6 integration (§8.6) | `outreach_coordinator.priority(session, case)` — the D-098 seam — now returns `compute_recovery_score(...).score`. `merge._ordered(session, items)` and `human_queue.enqueue` consume it through that seam only; no consumer re-derives the formula (INV-56 / D-113). Three Module 6 tests updated off the `amount_at_risk` placeholder. |
| State machine / guards | **byte-unchanged.** Module 8 adds no transition and no guarded field. |

**Modules 9–13 not started.** The Module 8 run is **uncommitted**.

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`dd995d2`** (committed Module 7). Module 8 changes sit uncommitted on top. |
| Working tree | Module 8. Modified: `src/torque/config.py` (`recovery_score_cost_floor`), `src/torque/exceptions.py` (`RecoveryScoreError`), `src/torque/models/revenue_leak_case.py` (+3 derived columns), `src/torque/coordination/{outreach_coordinator,human_queue,merge}.py` (the `priority()` seam → real score, `(session, case)`), `src/torque/diagnosis/engine.py` + `src/torque/ingestion/{cases,checkout,subscription,b2b,celery_app}.py` (inline `score_case` + the daily beat entry), `tests/test_module6_human_queue.py` / `tests/test_module6_outreach_coordinator.py` (3 assertions off the placeholder), `tests/test_schema_introspection.py` (+3 Module 8 assertions). New: `src/torque/scoring/` (5 files), `migrations/versions/0017_recovery_score.py`, 6 `tests/test_module8_*.py`. |
| Alembic head / current | **`0017_recovery_score`** — Module 8 added one migration (3 nullable columns, no enum). |
| Test suite | **1007 passed** (`uv run pytest -q`), 0 fail / 0 skip. 1 cosmetic `StarletteDeprecationWarning` (pre-existing). |
| `def test_` functions | **834** (was 772) |
| Lint | `uv run ruff check .` → clean |
| Migration roundtrip | green (up→down→up incl. 0017) |
| `src/torque/models/guards.py` | **`git diff HEAD --` empty** — byte-unchanged. |
| `src/torque/state_machine.py` | **`git diff HEAD --` empty** — byte-unchanged. |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI, Celery + Redis + beat, PostgreSQL 16, `uv`, pytest, ruff |
| DB / infra | Postgres host **5442**; Redis host **6389**. Tests run eager/mocked. **25 tables** (unchanged — Module 8 added columns, not a table). |

## What is implemented (new in Module 8)

- **`torque.scoring`** package: `benchmarks.py` (Decision F cold-start lookup +
  §8.2 warm-start multiplier), `cost.py` (`compute_cost` / `CostBreakdown` — the
  forward `ChannelRateCard` cost), `score.py` (`RecoveryScore`,
  `compute_recovery_score`, `score_case`, `recompute_open_cases`), `tasks.py`
  (`recompute_recovery_score_task`, `recompute_open_case_scores_task`),
  `__init__.py`.
- **Migration 0017** — the three `recovery_score*` columns on `revenue_leak_case`.
- **`PolicyConfig.recovery_score_cost_floor`** (0.01); **`RecoveryScoreError`**.
- **Seam:** `outreach_coordinator.priority(session, case)` → the real score;
  `human_queue` / `merge` updated to pass the session.
- **Recompute wiring:** inline `score_case` in the 4 ingestion paths + the
  diagnosis engine; one Celery-beat entry + `torque.scoring` autodiscover.

Full breakdown: `ARCHITECTURE.md` §8H.

## Next milestone

**Module 9 — Reporting & Measurement.** ₹ recovered by leg, recovery rate,
incrementality lift with a **Wilson score CI**, the SUTVA-adjusted lift, the
exception list (`Action`s `BLOCKED_BY_GUARDRAIL` grouped by `block_reason`), cost
efficiency, and the mechanical explainability panel (a query over the `CaseEvent`
stream, `event_seq_id` order). Module 8's `recovery_score` /
`recovery_score_breakdown` columns are ready for the "top at-risk cases" view.
Do not start without an approved scope.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`.
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** (Module 8 surfaced
   U-09 — the scoring calibration defaults — rather than claiming them settled.)
6. `state_machine.py` / `guards.py` are load-bearing. Changing either needs
   explicit approval + a shown diff. (Module 8 changed **neither**.)
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01** — FULLY RESOLVED (Module 7, D-103 + M7c, D-066).
- **U-02 / U-07** — RESOLVED (Module 5).
- **U-03** — Tier 1 vs Tier 3 MAC precedence — stated default. Open.
- **U-04** — systemic N / M / sustain numbers are placeholders. Open.
- **U-05 / U-06** — Part D items; `MacCodeRegistry` unseeded codes. Open.
- **U-08** — issuer / BIN / acquirer / route extraction; blocks `ISSUER_SPECIFIC`
  systemic detection and the §5.3 first-touch MAC lookup (D-083). Open.
- **U-09** — **NEW** — Module 8's calibration values (warm-start normalisation
  shape, the 0.5×–1.3× cap, the ₹0.01 cost floor, the `amount_bucket`
  thresholds) are stated defaults, not derived from Torque data. Not blocking.

## Known contradictions / caveats

- **`README.md` is stale.** Trust `CURRENT_STATE.md` / the code.
- **Module 8 is uncommitted** on top of committed Module 7 (`dd995d2`). Every
  "verified fact" above (1007 tests) reflects the working tree.
- **`priority()` changed signature** — `priority(session, case)` (was
  `priority(case)`). The DB session is needed for the real score (promise-keeping
  history, rate card, next playbook step). Three Module 6 tests updated (D-113) —
  behaviour preserved, only the score's *value* changed (the sanctioned Module 8
  deliverable).
- **`recovery_score` is a derived cache** — refreshed on creation / diagnosis /
  daily; between daily sweeps a `human_queue` entry's stored `priority` can lag a
  case whose bucket has aged. A live re-sort is a Module 10 concern (DEFERRED).
- **`amount_bucket` does not move the probability** — Decision F seeds no
  amount-tier variation; the dimension is kept for the breakdown / the §8.4
  learned-model feature set only (D-110).
- **Cost floors when the next step is free / unpriced** — a `RETRY_PAYMENT` next
  step (no channel) or a `payment_link` channel (no rate-card row) → `₹0.01`
  divisor. Correct resource-aware ranking (cheap + likely + valuable ranks
  highest), just finite (D-111).
- **The executor is still a stub (§5.4).** Torque still fires no real messages or
  charges. Execution is still not auto-triggered (Module 2→3, 3→4, 4→5;
  D-080/D-088/D-093). Module 8's recompute triggers ARE wired inline (they only
  write a derived column — no status change, no CaseEvent).
- Module 1–7 caveats still stand.

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py src/torque/models/guards.py` —
expect **empty** on both), report any drift, then — once the maintainer has
committed Module 8 — propose **Module 9 — Reporting & Measurement** as one
continuous scope.
