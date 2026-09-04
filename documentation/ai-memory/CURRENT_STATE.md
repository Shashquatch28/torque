# CURRENT STATE — read this first

**Last updated:** 2026-09-04, after the **Module 12 — Build Roadmap** run
(**uncommitted, documentation-only**, on top of committed Modules 1–11 + 9b).
**Reconstructed from:** committed Modules 1–11 + 9b (HEAD `7172c92`) + the
uncommitted Module 12 documentation + `Torque_Blueprint_v7_FullSystem.md`.
**This file is derived documentation, not authoritative.** The repo and blueprint win.

---

## What Torque is

A revenue-leakage recovery agent closing the loop across four funnel legs —
**payment degradation, checkout abandonment, subscription/mandate failure, B2B
receivables** — with **one shared case object and one shared event ledger**. It
diagnoses root cause, runs a bounded recovery playbook under hard compliance
guardrails, reconciles incoming payments back to the leaking case, scores every
open case by its economic recovery opportunity, reports the business outcome
both **descriptively** (₹ recovered, recovery rate) and **causally**
(treatment-vs-control incremental lift with an honest confidence interval and
the SUTVA cross-merchant caveat), presents all of it as a runnable product on
one port, and ships that runtime as a reproducible free-tier `docker-compose`
stack. Full vision: `PROJECT_CONTEXT.md` §1. Spec:
`Torque_Blueprint_v7_FullSystem.md`. Product-pitch knowledge base:
`learning_log.md` (root).

## Where we are

**Modules 1–8 — COMPLETE & committed** (`8fbd97b` = Module 8).
**Modules 9 + 10 — COMPLETE & committed** (`7b89e36`).
**Module 11 — COMPLETE & committed** (`6c6392c`).
**Module 9b — COMPLETE & committed** (`7172c92`).
**Module 12 — Build Roadmap — COMPLETE** (this run, **uncommitted,
documentation-only** — no application code, no migration, no test changed).

Module 12 is not a code module: it classifies every remaining open item into
**A. demo-critical / B. demo-enhancing / C. production-hardening /
D. future-optional**, with a dependency graph and a recommended order. The full
breakdown lives in `DEFERRED.md` § "Build Roadmap Priority Classification" —
read it before proposing the next milestone. Summary:

| Category | Count | Headline |
|---|---|---|
| **A — demo-critical** | 1 | Wire the ingestion→diagnosis→policy-activation→execution auto-dispatch chain (D-080/D-088/D-093) — currently nothing chains these; a live-injected case dead-ends at `DETECTED`. LOW–MEDIUM complexity, no schema/state-machine change, no dependency. |
| **B — demo-enhancing** | 3 | Live cross-leg-merge / B2B-bundle demo scenarios (the blueprint's Module 13 script names this as a "Live:" beat); an A1-fallback; a bigger incrementality cohort. |
| **C — production-hardening** | 15 | Real channel adapters (needs 4 external accounts), the U-08-gated MAC lookup + `ISSUER_SPECIFIC` systemic detection, secrets management, CI/CD, Postgres RLS, DPDP intake, observability, etc. Roadmapped, **not implemented**. |
| **D — future/optional** | 8 | Real Temporal cluster (**D-090 not reopened**), learned uplift model (needs 500+ cases), CAU, SMS production path, NACH cross-instrument aggregation, and other genuinely non-critical items. |

**Verified already sufficient, no action needed:** Module 9 descriptive
reporting, Module 9b incrementality (API + dashboard both live), Module 10
Agent Console, Module 11 infra, and the compliance-guardrail demonstration
(the three Decision-K restraint scenarios already run real diagnosis + a real
guardrail block, live, on demand).

**Recommended next coding milestone:** an optional, small **"Module 12a —
Close the Autonomous Loop"** (item A1 + item B1 above) immediately before
**Module 13 — Demo Script**. Module 13 can proceed with or without it — the
system is demo-credible today — but 12a makes the live demo strictly stronger.
Do not start either without an approved scope.

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`7172c92`** "Module 9b: incrementality / causal measurement". Module 12 sits **uncommitted** on top (docs only). |
| Working tree (Module 12) | **Modified only:** `documentation/ai-memory/{MILESTONES,CURRENT_STATE,DEFERRED,ARCHITECTURE,DECISIONS}.md`, `README.md`. **Zero files under `src/` or `tests/` touched.** |
| Alembic head | **`0018_escalation_resolution`** — unchanged; Module 12 has no migration. |
| Test suite | **1209 passed** (`uv run pytest -q`), 0 fail / 0 skip. Unchanged from `7172c92` — no code touched. 1 pre-existing cosmetic `StarletteDeprecationWarning`. |
| Lint | `uv run ruff check .` → clean. |
| Migration roundtrip | green (`tests/test_zz_migrations_roundtrip.py`, incl. 0018). |
| `src/torque/state_machine.py` | **`git diff HEAD --` empty** — byte-unchanged (since M1). |
| `src/torque/models/guards.py` | **`git diff HEAD --` empty** — unchanged since the Module 10 `human_resolution_writer`. |
| `docker-compose.yml` services | Confirmed live: `db, redis, migrate, api, worker, beat` (Module 11, unchanged). |
| `GET /reports/{m}/incrementality` | Confirmed live in `src/torque/api/reporting.py`, fetched + rendered by `torque.js`'s `incrementalityCard` (Module 9b, unchanged). |
| D-090 | Confirmed `Status: IN FORCE` in `DECISIONS.md` — Postgres-polling remains the durable `PlaybookRun` driver; **not reopened**. |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI + StaticFiles, Celery + Redis (broker only) + beat, PostgreSQL 16, `uv`, pytest, ruff, `Dockerfile` + full `docker-compose`. No Node, no Temporal. |
| DB / infra | Postgres host **5442**; Redis host **6389**; API **8000** (compose `full` profile). **25 tables** (unchanged). |

## What is implemented (Module 12)

Nothing in application code — Module 12 is a documentation/planning milestone.
It produced:
- `documentation/ai-memory/DEFERRED.md` § "Build Roadmap Priority
  Classification" — the full A/B/C/D breakdown, per-item fields, and the
  dependency graph.
- `documentation/ai-memory/DECISIONS.md` **D-136** — the classification rule
  and the specific priority calls (most notably A1 ranked above every
  Category-C item).
- This snapshot, `MILESTONES.md`'s Module 12 section, and a pointer in
  `README.md`.

## How to run the product locally

Unchanged from Module 11 — see `README.md` ("Setup — host dev loop" / "Run the
full stack in containers"). No new run path was introduced.

## Next milestone

Two live options, **not started**, waiting on maintainer approval:
1. **"Module 12a — Close the Autonomous Loop"** (recommended first) — wire
   the auto-dispatch chain (A1) + add the two live cross-leg/B2B demo
   scenarios (B1). See `DEFERRED.md` for the exact scope.
2. **Module 13 — Demo Script** — can proceed directly; still needs Part D
   item 4 (a real judging rubric, if one exists — U-05).

Category C (production-hardening) and D (future/optional) items are
roadmapped, not scheduled — see `DEFERRED.md` for triggers/ordering.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`. (Module 12: no deviation — it answers
   the ordering question the blueprint's own Module 12 needed Part D item 3 to
   answer with dates, which is still unanswered — U-05 item 3.)
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.** (Module 12 itself
   is proof of this: it classifies and orders without building anything.)
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** Module 12
   resolved **none** — U-08 is cross-referenced as a shared blocker for two
   Category-C items, not answered.
6. `state_machine.py` / `guards.py` are load-bearing. **Module 12 touched
   neither** (no code touched at all).
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01 / U-02 / U-07 / U-10** — RESOLVED.
- **U-05** — Part D items 1–2 RESOLVED. Items 3 (build-window length) and 4
  (judging rubric) still open — Module 12 could not answer item 3 either (no
  calendar plan was produced, only a priority/dependency ordering); both block
  only Modules 12a/13's exact scheduling, not their content.
- **U-03 / U-04 / U-06** — open (MAC precedence, systemic N/M numbers, unseeded
  MAC codes). None constrain Module 12a or Module 13.
- **U-08** — open; now explicitly the shared blocker for two `DEFERRED.md`
  Category-C items (MAC first-touch lookup, `ISSUER_SPECIFIC` systemic
  detection). Not resolved by this run.
- **U-09** — Module 8 calibration values are stated defaults. Not blocking.
- **U-11** — Agent Console vocabulary choices. Not blocking.
- **D-090 (Postgres-polling over Temporal)** — **IN FORCE**, reaffirmed by
  D-127 (Module 11), **not reopened** by Module 12.

## Known contradictions / caveats

- **Module 12 is uncommitted** on top of committed Modules 1–11 + 9b
  (`7172c92`). It changes documentation only — every "verified fact" above
  (1209 tests, `0018` head, both load-bearing diffs empty) is identical to
  `7172c92`'s, by construction.
- **A live-injected case does not currently self-diagnose.** The
  `payment_failure` / `checkout_abandonment` demo scenarios (and any real
  ingestion) create a genuine `DETECTED` case and then stop — nothing
  auto-dispatches diagnosis (D-080), activation (D-088), or scheduling
  (D-093). This is a **known, documented** limitation (not new to Module 12 —
  every module since Module 3 has deferred it), now ranked the top item
  (A1) in `DEFERRED.md`'s roadmap. The demo is still credible today via the
  three Decision-K restraint scenarios (which *do* drive real diagnosis +
  guardrail-blocking inline) and the static 16-case seed.
- **No live cross-leg-merge or B2B-bundle demo trigger exists** — only the
  static seed shows one. Ranked B1.
- **README.md / `CURRENT_STATE.md` Module 11 framing still applies** — Redis
  broker-only, no Temporal, host + full-stack run paths unchanged.
- **The executor is still a stub (§5.4).** Torque fires no real messages /
  charges; unchanged by Module 12 — roadmapped as Category C (item C1).
- **No Temporal** (D-090 / D-127). **No browser/e2e harness** (D-122).
- **`Action.cost` is still ~0** — a Category-C item (C3), downstream of C1.
- Module 1–11 + 9b caveats still stand (UI computes nothing; "Cancel" =
  `WRITTEN_OFF`; demo `reset` disables the `case_event` trigger for its scoped
  wipe over both demo merchant ids; large `recovery_score` values for unpriced
  open cases; pre-existing suite flakiness under load; two recovery
  definitions coexist deliberately — Module 9 attributed vs. Module 9b
  intent-to-treat).

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py` and `-- src/torque/models/guards.py`
— **both expected empty**), report any drift, then — once the maintainer has
committed Module 12 and chosen — propose **"Module 12a — Close the Autonomous
Loop"** and/or **Module 13 — Demo Script** as one continuous scope. Do not
propose any Category-C or Category-D item as the next milestone without the
maintainer explicitly asking for production-hardening work.
