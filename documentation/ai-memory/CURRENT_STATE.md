# CURRENT STATE — read this first

**Last updated:** 2026-09-04, after the **Module 10 — UI/UX** run (uncommitted,
on top of accepted-but-uncommitted Module 9, on committed Module 8 `8fbd97b`).
**Reconstructed from:** committed Modules 1–8 (HEAD `8fbd97b`) + the uncommitted
Module 9 + Module 10 changes + `Torque_Blueprint_v7_FullSystem.md`.
**This file is derived documentation, not authoritative.** The repo and blueprint win.

---

## What Torque is

A revenue-leakage recovery agent closing the loop across four funnel legs —
**payment degradation, checkout abandonment, subscription/mandate failure, B2B
receivables** — with **one shared case object and one shared event ledger**. It
diagnoses root cause, runs a bounded recovery playbook under hard compliance
guardrails, reconciles incoming payments back to the leaking case, scores every
open case by its economic recovery opportunity, reports the business outcome, and
— new in Module 10 — **presents all of it as a runnable product**: a merchant
dashboard, an agent console, and a live demo surface, served by the same process
on one port. Full vision: `PROJECT_CONTEXT.md` §1. Spec:
`Torque_Blueprint_v7_FullSystem.md`. Product-pitch knowledge base:
`learning_log.md` (root).

## Where we are

**Modules 1–8 — COMPLETE & committed** (`8fbd97b`).
**Module 9 — Reporting & Measurement — COMPLETE, accepted, uncommitted.**
**Module 10 — UI/UX — §10 — COMPLETE** (this run, **uncommitted**).

| Module 10 capability | Behaviour |
|---|---|
| Frontend stack (D-122) | A hand-written **static SPA** — `src/torque/ui/static/{index.html,torque.css,torque.js}` (vanilla JS, no framework, no bundler), mounted with `StaticFiles` at `/ui` by `create_app()`. `GET /` → `/ui/`. Hash routing. **No new runtime dependency.** Runs with `uv run python -m torque` (one process, one port). |
| Merchant Dashboard (§10.1–10.3, 10.11) | Hero ₹-recovered (dominant); stat tiles (revenue at risk, recovery rate, unresolved, human escalations, blocked/deferred amount, cost efficiency); recovery-by-leg table; a CSS bar chart of recovery-over-time; the top-at-risk ranked list (Module 8 `recovery_score` order, backend); "Where Torque deliberately held back" (exception list, surfaced prominently). `SELF_RECOVERED` shown separately, never in the headline; no "actions = revenue" framing. |
| Case detail / explainability (§10.5–10.6) | Overview card + a "WHY THIS CASE?" panel rendering `recovery_score_breakdown.explain` **verbatim** (probability × amount ÷ expected cost = priority score + the "why" lines) + the full `CaseEvent` timeline in `event_seq_id` order. |
| Agent Console (§10.7–10.8) | The human queue (priority order from the backend) + a case pane with pause / unpause / **resolve** controls. `torque.agent_console.resolve_escalation`: `ESCALATED_TO_HUMAN → {RECOVERED | PARTIALLY_RECOVERED | WRITTEN_OFF}` (edges already legal — §4), sets `escalation_resolution` / `_by` / `_at`, writes a `HUMAN_RESOLVED` `CaseEvent` (`actor=HUMAN`), a recovering resolution also sets `recovered_amount` / `recovery_type = AGENT_ASSISTED` inside `guards.human_resolution_writer`, and the case leaves the queue. "Cancel" = resolve → `WRITTEN_OFF` (D-124). pause/unpause = `PLAYBOOK_ACTIVE ↔ PAUSED`. INV-59. |
| Demo Surface (§10.9–10.10, 10.16) | `torque.demo.seed_demo` — a fixed 16-case `acc_demo` dataset (all 4 legs; recovered / self-paid / B2B-partial / blocked / deferred / escalated / exhausted / open; each with a `CaseEvent` trail; all Module-8 scored; deterministic clock `DEMO_NOW`; idempotent; `reset=true` disables the `case_event` trigger for the wipe — D-125). `torque.demo.inject_scenario` — one-click checkout / payment-failure / Decision-K hard-stop-MAC / UPI-cap / NACH-ceiling, composing the **real** ingestion + compliance code (each restraint scenario asserts the real predicate blocks). Live feed = polling `/reports/{m}/activity` every 3 s. |
| New backend endpoints (§10.13) | `GET /reports/{m}/top-at-risk` · `/human-queue` · `/activity` (Module 9 router, GET, tenant-scoped); `POST /agent-console/{m}/cases/{cid}/{resolve\|pause\|unpause}`; `POST /demo/seed`, `GET /demo/scenarios`, `POST /demo/inject/{key}`, `GET /demo/merchant`. `case_detail` enriched (`recovery_score_breakdown`, `recovery_probability`, `counterparty_label`, `root_cause_code`, `escalation_*`). |
| Migration | **`0018_escalation_resolution`** — 3 nullable `VARCHAR(64)`/`TIMESTAMPTZ` columns on `revenue_leak_case`. No table, no enum, no `CaseEventType` (`HUMAN_RESOLVED` already existed; count stays 10). D-123. |
| State machine | **byte-unchanged** — the resolve targets and `PLAYBOOK_ACTIVE ↔ PAUSED` are already-legal §4 edges. |
| `guards.py` | **CHANGED** — `human_resolution_writer(session)` + an `hr` flag in `_guard_case` (`not (m7 or hr)`), mirroring `network_directive_writer`. Required (a human `→ RECOVERED` writes guarded fields), reported, D-123. First `guards.py` change since M6a. |
| Live updates (§10.17) | **Polling** — no WebSocket (backend has no push channel; simplest reliable — D-124). |

**Modules 11–13 not started.**

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`8fbd97b`** (committed Module 8). Module 9 + Module 10 changes sit uncommitted on top. |
| Working tree | Module 9 (uncommitted, accepted) + Module 10. New (Module 10): `src/torque/agent_console/` (2 files), `src/torque/demo/` (3 files), `src/torque/ui/static/` (3 files), `src/torque/api/{agent_console,demo,ui}.py`, `migrations/versions/0018_escalation_resolution.py`, 6 `tests/test_module10_*.py`. Modified (Module 10): `src/torque/api/app.py`, `src/torque/api/reporting.py`, `src/torque/reporting/{metrics,schemas,__init__}.py`, `src/torque/models/{revenue_leak_case,guards}.py`, `src/torque/exceptions.py`, `tests/test_schema_introspection.py`. |
| Alembic head | **`0018_escalation_resolution`** — Module 10 added one migration (3 nullable columns, no enum). |
| Test suite | **1109 passed** (`uv run pytest -q`), 0 fail / 0 skip. 1 cosmetic `StarletteDeprecationWarning` (pre-existing). *(Pre-existing intermittent cross-test isolation flakiness — see Module 9 notes — still present; unrelated to Module 10.)* |
| Lint | `uv run ruff check .` → clean. No frontend lint/typecheck/build (D-122 — no TS, no build). |
| Migration roundtrip | green (up→down→up incl. 0018) |
| `src/torque/state_machine.py` | **`git diff HEAD --` empty** — byte-unchanged. |
| `src/torque/models/guards.py` | **CHANGED** — the `human_resolution_writer` addition only (D-123). |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI + StaticFiles, Celery + Redis + beat, PostgreSQL 16, `uv`, pytest, ruff. **No Node.** |
| DB / infra | Postgres host **5442**; Redis host **6389**. **25 tables** (unchanged — Module 10 added columns, not a table). |

## What is implemented (new in Module 10)

- **`torque.ui`** — `mount_ui(app)` + the static SPA (`ui/static/`).
- **`torque.agent_console`** — `resolve.py` (`resolve_escalation`, `pause_case`,
  `unpause_case`, `EscalationResolution`).
- **`torque.demo`** — `seed.py` (`seed_demo`, `DEMO_MERCHANT_ID`, `DEMO_NOW`),
  `scenarios.py` (`inject_scenario`, `DEMO_SCENARIOS`).
- **`torque.api.{agent_console,demo,ui}`** — the routers, wired into `app.py`.
- **`torque.reporting`** — `top_at_risk_cases`, `human_queue_list`,
  `recent_activity`; `case_detail` enriched.
- **Migration 0018** + `guards.human_resolution_writer` +
  `exceptions.{CaseNotFoundError,HumanResolutionError}`.

Full breakdown: `ARCHITECTURE.md` §8J.

## How to run the product locally

```
docker compose up -d db                    # Postgres on :5442
uv run alembic upgrade head                # → 0018
uv run python -m torque                    # API + UI on http://127.0.0.1:8000
curl -X POST http://127.0.0.1:8000/demo/seed        # deterministic acc_demo dataset
# open http://127.0.0.1:8000/  → redirects to /ui/  (defaults to acc_demo)
```

Or skip the `curl`: open `/ui/`, go to **Live Demo**, click **Seed demo data**,
then **Dashboard**. `POST /demo/seed?reset=true` rebuilds from scratch.

## Next milestone

**Module 11 — Tech Stack & Infra** (consolidate deployment: Temporal-vs-fallback
go/no-go, prod queue, `docker-compose` worker/beat services) and/or **Module 13
— Demo Script**, plus **Module 9b — Incrementality** (D-121 / U-10). Do not start
without an approved scope.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`. (Module 10: no substantive deviation —
   the blueprint's §10 is 3 bullets; D-122/D-124 pick the faithful minimum.)
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** (Module 10 surfaced
   U-11 — the Agent Console override vocabulary / pause target — rather than
   claiming it settled.)
6. `state_machine.py` / `guards.py` are load-bearing. **Module 10 changed
   `guards.py`** (the one §10.8-assigned human-resolution write path — D-123,
   diff shown); `state_machine.py` byte-unchanged.
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01 / U-02 / U-07** — RESOLVED.
- **U-03 / U-04 / U-05 / U-06 / U-08** — open (MAC precedence, systemic numbers,
  Part D items, issuer extraction).
- **U-09** — Module 8 calibration values are stated defaults. Not blocking.
- **U-10** — incrementality / causal measurement deferred to "Module 9b". Not
  blocking.
- **U-11** — **NEW** — Agent Console `escalation_resolution` vocabulary and the
  pause/cancel target states are Module-10 choices the blueprint underspecifies
  (D-123 / D-124). Not blocking.

## Known contradictions / caveats

- **`README.md` is stale.** Trust `CURRENT_STATE.md` / the code.
- **Module 9 + Module 10 are uncommitted** on top of committed Module 8. Every
  "verified fact" (1109 tests) reflects the working tree.
- **`guards.py` changed** — `human_resolution_writer`, the parallel gate to
  `module7_writer` for a human resolution's `recovery_type` / `recovered_amount`
  write (D-123). `state_machine.py` untouched.
- **The UI computes nothing** — every metric, score and ranking comes from the
  backend; `torque.js` only fetches, formats and renders (§10.4 / §10.13).
- **"Cancel" is a write-off** — an escalated case a human gives up on goes to
  `WRITTEN_OFF`, not `CANCELLED` (which is reserved for reconciliation-detected
  self-payment). D-124 / U-11.
- **Live feed is polling** (3 s) — no push channel exists (D-124).
- **No browser/e2e test harness** — the DOM logic is verified via its API
  contract + shell/wiring assertions (D-122); a Playwright layer is deferred.
- **Demo `reset` disables the `case_event` trigger** for its scoped wipe (D-125)
  — demo-only, single-merchant; the production append-only guarantee is untouched.
- **`recovery_score` values look large** next to `amount_at_risk` for open cases
  whose next step has no priced channel (cost floors to ₹0.01 — Module 8 D-111).
  The UI labels the column "Score" (a priority ordinal), not "₹". Faithful to
  Module 8; a NOTE, not a bug.
- **Pre-existing suite flakiness** (celery-eager `session_scope()` commits +
  `test_module6_merge`'s two-connection cleanup) — occasionally fails a small,
  different set of Module 2/4/6 tests across full runs; reproduces without
  Module 10; all pass in isolation.
- **The executor is still a stub (§5.4).** Torque still fires no real messages /
  charges; execution is not auto-triggered (D-080/D-088/D-093). The demo
  scenarios compose ingestion + compliance directly.
- Module 1–9 caveats still stand.

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py` — expect **empty**;
`git diff HEAD -- src/torque/models/guards.py` — expect the
`human_resolution_writer` addition only), report any drift, then — once the
maintainer has committed Modules 9 + 10 — propose **Module 11 — Tech Stack &
Infra** (or Module 13 / Module 9b) as one continuous scope.
