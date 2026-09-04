# CURRENT STATE — read this first

**Last updated:** 2026-09-04, after the **Module 9b — Incrementality / Causal
Measurement** run (**uncommitted**, on top of committed Modules 1–11).
**Reconstructed from:** committed Modules 1–11 (HEAD `6c6392c`) + the uncommitted
Module 9b changes + `Torque_Blueprint_v7_FullSystem.md`.
**This file is derived documentation, not authoritative.** The repo and blueprint win.

---

## What Torque is

A revenue-leakage recovery agent closing the loop across four funnel legs —
**payment degradation, checkout abandonment, subscription/mandate failure, B2B
receivables** — with **one shared case object and one shared event ledger**. It
diagnoses root cause, runs a bounded recovery playbook under hard compliance
guardrails, reconciles incoming payments back to the leaking case, scores every
open case by its economic recovery opportunity, reports the business outcome
(descriptive **and** — new in Module 9b — **causal**: treatment-vs-control lift
with an honest confidence interval and the SUTVA cross-merchant caveat),
presents all of it as a runnable product on one port, and ships that runtime as
a reproducible free-tier `docker-compose` stack. Full vision:
`PROJECT_CONTEXT.md` §1. Spec: `Torque_Blueprint_v7_FullSystem.md`.
Product-pitch knowledge base: `learning_log.md` (root).

## Where we are

**Modules 1–8 — COMPLETE & committed** (`8fbd97b` = Module 8).
**Modules 9 + 10 — COMPLETE & committed** (`7b89e36`).
**Module 11 — Tech Stack & Infra — COMPLETE & committed** (`6c6392c`).
**Module 9b — Incrementality / Causal Measurement — COMPLETE** (this run,
**uncommitted**) — an additive extension of Module 9.

| Module 9b capability | Behaviour |
|---|---|
| Causal layer (NEW module `torque.reporting.incrementality`) | `incrementality_report(session, merchant_id, *, window=None, leg=None)` → `IncrementalityReport`. **Cohort** = the per-case `RevenueLeakCase.control_group` snapshot (`True` control / `False` treatment / `None` excluded) — **no new cohort-assignment mechanism**, `sync_control_group` untouched. **Recovery** for the causal comparison = intent-to-treat `status ∈ {RECOVERED, CANCELLED}` (D-133) — deliberately broader than Module 9's Torque-attributed `recovery_rate` (which is **unchanged**), so the held-out control has a real self-recovery baseline. **Window** = the Module 9 `opened_at` half-open `ReportWindow`. |
| Headline lift | `incremental_lift = treatment_recovery_rate − control_recovery_rate`. Response exposes treatment/control `successes` / `total` / `rate`, the `lift.point`, and enough for the UI to explain the window (`opened_from`/`opened_to`/`window_basis="opened_at"`). Exact `Decimal`, quantised 4 dp. |
| Confidence interval (D-134) | **Wilson score interval** per cohort proportion (clamped `[0,1]`); **Newcombe (1998) hybrid score interval** for the lift (clamped `[-1,1]`). **95% two-sided**, `z = Φ⁻¹(0.975) ≈ 1.959963984540054` (`statistics.NormalDist`, stdlib). `total == 0` → `rate` / bounds `null` (never `NaN`/`inf`). `confidence_level` + `z_value` in the response. |
| SUTVA-adjusted lift (Blueprint §6, D-133/D-135) | The control cohort with every counterparty that **also** has a treatment case (`control_group = False`) at a **different** merchant in the same window removed; treatment untouched; **headline lift always kept alongside**. `sutva.contaminated_control_counterparties` / `excluded_control_cases` / adjusted `control` / adjusted `lift` / `note`. The one cross-merchant read selects only `counterparty_id`, bounded to the caller's own control counterparties, reduced to a `set` — no other merchant's id / amounts / outcomes / counts leave it. |
| API | **`GET /reports/{merchant_id}/incrementality`** (`opened_from`/`opened_to`/`leg`) — read-only, `TenantScope`d, same conventions as the rest of the Module 9 router (unknown merchant → 404, bad `leg` → 422). Router stays GET-only. **No existing Module 9 field renamed or removed.** |
| UI | A compact **"Incrementality — estimated causal effect"** card on the dashboard (`incrementalityCard(inc)` in `torque.js`, styles in `torque.css`): treatment rate, control rate, incremental lift + 95% CI, SUTVA-adjusted lift + CI + contaminated count, the honest SUTVA note + recovery definition, and an explicit "descriptive = what happened / causal = estimated incremental effect … not proof of causation" line. **Renderer only** — no rate/lift/interval computed in JS. |
| Demo (D-135) | `seed.py` now assigns every demo counterparty a cohort via the existing `assign_cohort` (3/16 held out as control) and adds a companion merchant **`acc_demo_up`** treating 2 of those control counterparties in-window so the SUTVA number is live. `DEMO_MERCHANT_IDS`; `_wipe` loops both. `acc_demo`'s descriptive numbers + 16-case count are byte-identical to before. |
| Migration | **none.** `alembic head` stays `0018_escalation_resolution`. |
| State machine / guards | **byte-unchanged vs HEAD** (`git diff HEAD --` empty for both). Module 9b adds no transition, guard, guarded field, or write path. |

**Modules 12–13 (Build Roadmap, Demo Script) not started.**

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`6c6392c`** "Module 11: tech stack & infra — reproducible runtime". Module 9b changes sit **uncommitted** on top. |
| Working tree (Module 9b) | **New:** `src/torque/reporting/incrementality.py`, `tests/module9b_helpers.py`, `tests/test_module9b_{wilson,incrementality,sutva,api,ui}.py`. **Modified:** `src/torque/reporting/{__init__,schemas}.py`, `src/torque/api/reporting.py`, `src/torque/ui/static/{torque.js,torque.css}`, `src/torque/demo/seed.py`, plus `documentation/ai-memory/*`. |
| Alembic head | **`0018_escalation_resolution`** — Module 9b adds no migration. |
| Test suite | **1209 passed** (`uv run pytest -q`), 0 fail / 0 skip. 1 pre-existing cosmetic `StarletteDeprecationWarning`. Was 1144 at `6c6392c`; **`+65`** (`test_module9b_*`: 27 wilson + 17 incrementality + 8 sutva + 10 api + 4 ui — minus parametrize double-count vs the flat 65). |
| Lint | `uv run ruff check .` → clean. |
| Migration roundtrip | green (`tests/test_zz_migrations_roundtrip.py`, incl. 0018). |
| `src/torque/state_machine.py` | **`git diff HEAD --` empty** — byte-unchanged (since M1). |
| `src/torque/models/guards.py` | **`git diff HEAD --` empty** — unchanged since the Module 10 `human_resolution_writer` (committed at `7b89e36`). |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI + StaticFiles, Celery + Redis (broker only) + beat, PostgreSQL 16, `uv`, pytest, ruff, `Dockerfile` + full `docker-compose`. **No Node. No Temporal.** No new dependency in Module 9b (`statistics.NormalDist` is stdlib). |
| DB / infra | Postgres host **5442**; Redis host **6389**; API **8000** (compose `full` profile). **25 tables** (unchanged). |

## What is implemented (new in Module 9b)

- **`torque.reporting.incrementality`** — `incrementality_report`, plus pure
  `wilson_interval` / `newcombe_difference`.
- **`torque.reporting.schemas`** — `ProportionCI`, `LiftEstimate`,
  `SutvaAdjustment`, `IncrementalityReport` (all additive, frozen).
- **`GET /reports/{merchant_id}/incrementality`** in `torque.api.reporting`.
- Dashboard **incrementality card** (`torque.js` / `torque.css`), renderer-only.
- Demo seed **cohort assignment** + the **`acc_demo_up`** SUTVA fixture.

Full breakdown: `ARCHITECTURE.md` §8I (Module 9b extension).

## How to run the product locally

**Host dev loop:**

```
docker compose up -d db redis
uv run alembic upgrade head                # → 0018
uv run python -m torque                    # API + UI on http://127.0.0.1:8000
curl -X POST http://127.0.0.1:8000/demo/seed?reset=true
# open http://127.0.0.1:8000/  → /ui/  → dashboard shows the descriptive
#   metrics AND the "Incrementality — estimated causal effect" card
curl -s http://127.0.0.1:8000/reports/acc_demo/incrementality
```

**Full containerised runtime (Module 11):**

```
cp .env.example .env
docker compose --profile full up --build   # db + redis + migrate + api + worker + beat
```

## Next milestone

**Module 12 — Build Roadmap** (phase → calendar plan; needs Part D item 3 —
build-window length) and/or **Module 13 — Demo Script** (needs Part D item 4 —
judging rubric; §9.3 places the SUTVA caveat as a deliberate beat, now backed by
a live number). Do not start without an approved scope.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`. (Module 9b: no deviation — Blueprint §6 /
   §9.1 specify the metric, the Wilson requirement, and the SUTVA rule; D-134
   fills the two gaps the blueprint leaves — confidence level, difference method
   — with the standard choices.)
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** (Module 9b resolved
   only **U-10** — the maintainer's approved scope — and left every other U-item
   untouched. D-121 preserved as historical.)
6. `state_machine.py` / `guards.py` are load-bearing. **Module 9b touched
   neither** (`git diff HEAD --` empty for both).
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01 / U-02 / U-07 / U-10** — RESOLVED.
- **U-05** — Part D item 1 (synthetic injection) + item 2 (Python, D-126)
  RESOLVED. Items 3–4 (build window, judging rubric) open — Modules 12–13.
- **U-03 / U-04 / U-06 / U-08** — open (MAC precedence, systemic N/M numbers,
  Part D residue, issuer extraction). None constrain Modules 12–13.
- **U-09** — Module 8 calibration values are stated defaults. Not blocking.
- **U-11** — Agent Console `escalation_resolution` vocabulary / pause target are
  Module-10 choices the blueprint underspecifies (D-123 / D-124). Not blocking.
- **D-090 (Postgres-polling over Temporal)** — **IN FORCE** (reaffirmed by D-127,
  Module 11). Do not reopen.

## Known contradictions / caveats

- **Module 9b is uncommitted** on top of committed Modules 1–11 (`6c6392c`).
  Every "verified fact" (1209 tests) reflects the working tree.
- **Two recovery definitions now coexist, deliberately:** Module 9's descriptive
  `recovery_rate` is Torque-**attributed** (`recovery_type != SELF_RECOVERED` —
  D-116). Module 9b's causal `treatment`/`control` rates are **intent-to-treat**
  (`status ∈ {RECOVERED, CANCELLED}` — D-133). The API's `recovery_definition`
  string and the UI both spell this out; they are never the same number.
- **The SUTVA adjustment is cross-merchant by design.** It reads, across all
  merchants, only `(counterparty_id, control_group, opened_at)` and only for the
  caller's own control counterparties, returning a `set` of contaminated ids.
  No other merchant's identity, amounts, outcomes, or counts reach any response
  field (INV-58 extension; `tests/test_module9b_sutva.py` / `_api.py`).
- **Incrementality is merchant-wide on the dashboard.** A `?leg=` filter exists
  on the endpoint but is not surfaced in the UI (per §9.1 — one dashboard
  metric).
- **`README.md` refreshed for Module 11** (Setup / Stack / run paths). The
  historical "Milestone 1" framing higher up is superseded by this file.
- **Redis is broker-only.** No durable application state is ever in Redis.
- **The executor is still a stub (§5.4).** Torque fires no real messages /
  charges; execution is not auto-triggered (D-080/D-088/D-093). Module 9b changed
  nothing about this.
- **No Temporal** (D-090 / D-127). **No browser/e2e harness** (D-122) — the
  Module 9b UI card is verified via its API contract + a source-inspection test
  (no JS statistics).
- **`Action.cost` is still ~0** (Module 5 does not populate it) — Module 9's
  `total_action_cost` / `cost_efficiency_ratio` are a data gap, not a bug.
- Module 1–11 caveats still stand (UI computes nothing; "Cancel" = `WRITTEN_OFF`;
  demo `reset` disables the `case_event` trigger for its scoped wipe — now over
  both demo merchant ids; large `recovery_score` values for unpriced open cases;
  pre-existing suite flakiness under load).

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py` and `-- src/torque/models/guards.py`
— **both expected empty**), report any drift, then — once the maintainer has
committed Module 9b — propose **Module 12 — Build Roadmap** or **Module 13 —
Demo Script** as one continuous scope.
