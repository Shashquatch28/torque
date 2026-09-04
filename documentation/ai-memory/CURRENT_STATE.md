# CURRENT STATE — read this first

**Last updated:** 2026-09-04, after the **Module 12a — Close the Autonomous
Loop** run (**uncommitted**, on top of committed Modules 1–12).
**Reconstructed from:** committed Modules 1–12 (HEAD `fc813ab`) + the
uncommitted Module 12a changes + `Torque_Blueprint_v7_FullSystem.md`.
**This file is derived documentation, not authoritative.** The repo and blueprint win.

---

## What Torque is

A revenue-leakage recovery agent closing the loop across four funnel legs —
**payment degradation, checkout abandonment, subscription/mandate failure, B2B
receivables** — with **one shared case object and one shared event ledger**.
It **autonomously** diagnoses root cause, activates a bounded recovery
playbook, and schedules its first execution step — no manual trigger between
any of those stages as of this run — under hard compliance guardrails,
reconciles incoming payments back to the leaking case, scores every open case
by its economic recovery opportunity, reports the business outcome both
descriptively and causally, presents all of it as a runnable product on one
port, and ships that runtime as a reproducible free-tier `docker-compose`
stack. Full vision: `PROJECT_CONTEXT.md` §1. Spec:
`Torque_Blueprint_v7_FullSystem.md`. Product-pitch knowledge base:
`learning_log.md` (root).

## Where we are

**Modules 1–8 — COMPLETE & committed** (`8fbd97b` = Module 8).
**Modules 9 + 10 — COMPLETE & committed** (`7b89e36`).
**Module 11 — COMPLETE & committed** (`6c6392c`).
**Module 9b — COMPLETE & committed** (`7172c92`).
**Module 12 — Build Roadmap — COMPLETE & committed** (`fc813ab`,
documentation-only).
**Module 12a — Close the Autonomous Loop — COMPLETE** (this run,
**uncommitted**) — Module 12's top-ranked item (A1) + its one demo-enhancing
item (B1).

| Module 12a capability | Behaviour |
|---|---|
| Autonomous chain (A1, D-137/D-138) | A case created by **any** of the four ingestion legs now **automatically** flows `DETECTED → diagnosis → (PLAYBOOK_ACTIVE + a scheduled run) or ESCALATED_TO_HUMAN`, with no manual engine call. `torque.ingestion.tasks.dispatch_diagnosis` enqueues `diagnose_case_task` for the canonical case (correct across both §2.4 merge directions and B2B attach) once its own transaction commits; `diagnose_case_task` enqueues `activate_case_task` on `ROUTED_TO_PLAYBOOK`; `activate_case_task` calls `torque.execution.scheduler.schedule_run` **directly, same transaction** on `RUN_CREATED` — arming the existing, unchanged 10s/60s Postgres-polling beat pollers (D-090, not reopened). Resolves D-080 / D-088 / D-093. |
| The one bug this run found (D-138) | `dispatch_diagnosis` always enqueues with a 2 s `countdown`. Discovered **empirically** via the Docker smoke test: dispatching with no delay let a real worker run `diagnose_case_task` *before* the originating (demo/API-layer) request's transaction had committed — the task saw no case and silently `NOOP`'d. Fixed; re-verified green against the real stack. |
| Live demo scenarios (B1) | Two new one-click `torque.demo.scenarios` entries: **`cross_leg_merge`** (checkout abandonment then a matching-order payment failure for the same counterparty — the real forward §2.4 Merge) and **`b2b_invoice_bundle`** (two overdue invoices for the same counterparty — the real §3 grouping rule). `inject_scenario(dispatch=True)` (the API's default) routes the resulting case through the same autonomous chain above. |
| Migration | **none.** `alembic head` stays `0018_escalation_resolution`. |
| State machine / guards | **byte-unchanged vs HEAD** (`git diff HEAD --` empty for both). The chain drives only already-legal transitions the engines already produced. |

**Module 13 — Demo Script — not started.**

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`fc813ab`** "Module 12: build roadmap — classify all remaining work". Module 12a sits **uncommitted** on top. |
| Working tree (Module 12a) | **New:** `tests/test_module12a_autonomous_chain.py`. **Modified:** `src/torque/ingestion/{tasks,cases,buffer,checkout,subscription,b2b}.py`, `src/torque/diagnosis/tasks.py`, `src/torque/policy/tasks.py`, `src/torque/demo/scenarios.py`, `src/torque/api/demo.py`, `tests/conftest.py`, `tests/{test_diagnosis_task,test_module4_task,test_module10_demo}.py`, plus `documentation/ai-memory/*`. **Zero files under `src/torque/models/`, `state_machine.py`, or `guards.py`.** |
| Alembic head | **`0018_escalation_resolution`** — unchanged; Module 12a has no migration. |
| Test suite | **1230 passed** (`uv run pytest -q`), 0 fail / 0 skip. Was 1211 at `fc813ab`; **`+19`** (`test_module12a_autonomous_chain.py`), net **+19** overall (2 pre-existing tests strengthened, not added; the Module 10 all-scenarios parametrized test gained 2 cases from the 2 new `DEMO_SCENARIOS` keys, offset by other bookkeeping — see `MILESTONES.md` "Module 12a" for the exact count). 1 pre-existing cosmetic `StarletteDeprecationWarning`. |
| Lint | `uv run ruff check .` → clean. |
| Migration roundtrip | green (`tests/test_zz_migrations_roundtrip.py`, incl. 0018). |
| `src/torque/state_machine.py` | **`git diff HEAD --` empty** — byte-unchanged (since M1). |
| `src/torque/models/guards.py` | **`git diff HEAD --` empty** — unchanged since the Module 10 `human_resolution_writer`. |
| Docker smoke test | **Passed, and found a real bug (D-138), then re-verified green** after the fix — see `MILESTONES.md` "Module 12a" for the exact sequence. |
| Stack | Unchanged from Module 11: Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI + StaticFiles, Celery + Redis (broker only) + beat, PostgreSQL 16, `uv`, pytest, ruff, `Dockerfile` + full `docker-compose`. No Node, no Temporal, no new dependency. |
| DB / infra | Postgres host **5442**; Redis host **6389**; API **8000** (compose `full` profile). **25 tables** (unchanged). |

## What is implemented (new in Module 12a)

- **`torque.ingestion.tasks.dispatch_diagnosis`** — the ingestion → diagnosis
  enqueue, with the D-138 countdown.
- **`on_case_ready` hook** on `create_or_attach_case` / `create_checkout_case`
  / `create_subscription_case` / `ingest_invoice` (+ their buffer wrappers) —
  additive, default `None`, wired only by the Celery task layer.
- **`torque.diagnosis.tasks._dispatch_activation`** — the diagnosis → policy
  enqueue, fired only on `ROUTED_TO_PLAYBOOK`.
- **`torque.policy.tasks.activate_case_task`**'s inline `schedule_run` call on
  `RUN_CREATED` — the policy → execution hand-off, same transaction.
- **`torque.demo.scenarios`** — `cross_leg_merge`, `b2b_invoice_bundle`,
  `inject_scenario(..., dispatch=False)`.
- **`torque.api.demo.post_inject`** — now calls `inject_scenario(...,
  dispatch=True)`.

Full breakdown: `ARCHITECTURE.md` §8L.

## How to run the product locally

Unchanged from Module 11 — see `README.md`. The demo now additionally
demonstrates: inject `payment_failure` (or any "act"/B1 scenario) → wait a
couple of seconds → the case has diagnosed and (if confident) activated and
scheduled itself, with no manual step. The three Decision-K restraint
scenarios are unaffected (they already drove their own inline diagnosis +
guardrail block, synchronously, before this run).

## Next milestone

**Module 13 — Demo Script** — not started. Needs Part D item 4 (a real judging
rubric, if one exists — U-05) to set the ordering/emphasis; otherwise ready to
proceed using the five locked differentiators, now with a genuinely autonomous
live flow to show alongside the Decision-K restraint scenarios and the static
seed. Category C (production-hardening) and D (future/optional) items from
Module 12's roadmap remain roadmapped, not scheduled.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`. (Module 12a: no deviation — closes
   cross-module triggers the blueprint's own text (D-080/D-088/D-093) always
   expected an orchestration layer to wire, using only already-specified
   mechanisms.)
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.** (Module 12a
   implemented exactly A1 + B1 — nothing from Category C/D was pulled forward.)
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** Module 12a
   resolved none; U-08 untouched.
6. `state_machine.py` / `guards.py` are load-bearing. **Module 12a touched
   neither** (`git diff HEAD --` empty for both).
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

Unchanged from Module 12 — Module 12a resolved no `UNRESOLVED.md` item:
- **U-01 / U-02 / U-07 / U-10** — RESOLVED.
- **U-05** — Part D items 1–2 RESOLVED. Items 3 (build-window length) and 4
  (judging rubric) still open.
- **U-03 / U-04 / U-06** — open (MAC precedence, systemic N/M numbers, unseeded
  MAC codes). None constrain Module 13.
- **U-08** — open; the shared blocker for the two Category-C items Module 12
  identified (MAC first-touch lookup, `ISSUER_SPECIFIC` systemic detection).
- **U-09 / U-11** — open, not blocking.
- **D-090 (Postgres-polling over Temporal)** — **IN FORCE**, reaffirmed by
  D-127 (Module 11), **not reopened** by Module 12a (D-137's execution
  hand-off explicitly arms the existing `scheduled_job` mechanism, nothing else).

## Known contradictions / caveats

- **Module 12a is uncommitted** on top of committed Modules 1–12 (`fc813ab`).
  Every "verified fact" above (1230 tests, `0018` head, both load-bearing
  diffs empty) is the working tree's state.
- **The autonomous chain now runs in the real deployment**, not just in
  scripted demo scenarios — a real webhook creating a case will, within a
  couple of seconds, be diagnosed and (if confident) activated and scheduled,
  with no operator action. This was previously false (a documented,
  intentional gap since Module 3); it is now true.
- **The §2.5 systemic-hold/resume sweep is unchanged and NOT part of this
  chain** — a case it resumes to `DIAGNOSING` still needs its own separate
  diagnosis trigger. Deliberately out of Module 12a's scope (see
  `ARCHITECTURE.md` §8L).
- **`dispatch_diagnosis`'s 2 s countdown is a real, load-bearing detail**, not
  cosmetic — removing it would silently reintroduce D-138's race for the
  demo/API-layer caller (the ingestion-task-layer callers would still be safe
  either way, since they dispatch strictly after their own confirmed commit).
- **The executor is still a stub (§5.4).** Torque now *reaches* the point of
  scheduling a real execution step automatically, but `run_action` still
  performs no real I/O — unchanged, out of Module 12a's scope (Category C).
- **No Temporal** (D-090 / D-127). **No browser/e2e harness** (D-122).
- Module 1–12 caveats still stand (UI computes nothing; "Cancel" =
  `WRITTEN_OFF`; demo `reset` disables the `case_event` trigger for its scoped
  wipe over both demo merchant ids; two recovery definitions coexist
  deliberately — Module 9 attributed vs. Module 9b intent-to-treat; large
  `recovery_score` values for unpriced open cases; pre-existing suite flakiness
  under load; `Action.cost` still ~0).

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py` and `-- src/torque/models/guards.py`
— **both expected empty**), report any drift, then — once the maintainer has
committed Module 12a — propose **Module 13 — Demo Script** as the next
milestone. Do not propose any Category-C or Category-D item (see
`DEFERRED.md`'s "Build Roadmap Priority Classification") without the
maintainer explicitly asking for production-hardening work.
