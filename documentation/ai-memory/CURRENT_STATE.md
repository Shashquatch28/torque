# CURRENT STATE — read this first

**Last updated:** 2026-09-03, after the **Module 4 — Policy & Playbook Engine**
run (uncommitted).
**Reconstructed from:** the committed Module 3 (HEAD) + the uncommitted Module-4
run + `Torque_Blueprint_v7_FullSystem.md`.
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

**Module 1 (Core Data Model) — Part A — COMPLETE** (M1–M6b).
**Module 2 (Signal Ingestion) — Part B — COMPLETE & committed.** Four legs ingest
into canonical `RevenueLeakCase`s in `DETECTED`; bidirectional §2.4 Merge; §2.5
`NETWORK_WIDE` systemic detection.
**Module 3 (Diagnosis Engine) — §3 — COMPLETE & committed.** `torque.diagnosis`:
rule-based classification → `root_cause_code` + `diagnosis_confidence`, routed
`DIAGNOSING → PLAYBOOK_ACTIVE` (≥ T=0.65) or `→ ESCALATED_TO_HUMAN` (< T).
**Module 4 (Policy & Playbook Engine) — §4 — COMPLETE** (this run, uncommitted).
`torque.policy`: catalog + selection + version-pinned `PlaybookRun` instantiation.

| Module 4 capability | Behaviour |
|---|---|
| Catalog (§4.1) | 11 playbooks (`catalog.py`), ORM-seeded so graphs pass save-time validation (D-085); UPI AutoPay `max_attempts = 3` |
| Selection (§4.1) | `select_playbook_id(leg, root_cause, mandate_type)`; subscription NSF is rail-specific; "trivial" causes → `None` |
| Run instantiation | `activate_case`: pin latest version, `active_step_id = entry`, `status = RUNNING`, atomic, idempotent (one live run/case) |
| No playbook / disabled | `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN` via the existing legal edge (D-086) |
| Traversal rules (§4) | pure `entry_step_id`/`next_step_id`/`is_terminal`/`step_template` (`traversal.py`) — no execution |
| Payday (§4.3) | policy gate only (`payday.py`, `Merchant.risk_appetite_config`, D-087); timing computation is Module 5 |
| Multi-case (§4.4) | `step_template(node, multi_case)` → multi template or single + defer signal; reuses `ActionCase` |

**Modules 5–13 not started.** The Module-4 run is **uncommitted**.

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | the committed Module 3 (Module 4 sits uncommitted on top) |
| Working tree | uncommitted Module-4 run. New: `src/torque/policy/` (`__init__`, `catalog`, `selection`, `traversal`, `payday`, `engine`, `tasks`), `tests/test_module4_{catalog,selection,activation,versioning,resolution,traversal,payday,task}.py`. Modified: `src/torque/exceptions.py` (+`PlaybookGraphError`), `src/torque/ingestion/celery_app.py` (task registration). |
| Alembic head / current | **`0014_diagnosis_timing`** — **no Module-4 migration** (catalog ORM-seeded, payday flag in JSONB, multi_case_template in params). |
| Test suite | **754 passed** (`uv run pytest -q`), 0 fail / 0 skip. 1 cosmetic `StarletteDeprecationWarning`. |
| `def test_` functions | **632** |
| Lint | `uv run ruff check .` → clean |
| Migration roundtrip | green (up→down→up) |
| `src/torque/state_machine.py` | **byte-unchanged vs HEAD**. M4 uses the existing `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN` edge; run creation needs no transition. |
| `src/torque/models/guards.py` | **byte-unchanged vs HEAD**. |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI, **Celery + Redis + beat**, PostgreSQL 16, `uv`, pytest, ruff |
| DB / infra | Postgres host **5442**; Redis host **6389**. Tests run eager/mocked. |

## What is implemented (new in Module 4)

- **`torque.policy`** package: `catalog.py` (11 playbooks + `seed_catalog`),
  `selection.py` (`select_playbook_id`), `engine.py` (`activate_case`,
  `ActivationOutcome`, `resolve_effective_stopping_rules`), `traversal.py` (pure
  graph rules), `payday.py` (override policy gate), `tasks.py`
  (`activate_case_task`).
- **`exceptions.PlaybookGraphError`**; `celery_app` registers `torque.policy` tasks.

No schema change; 23 tables unchanged. Full breakdown: `ARCHITECTURE.md` §8D.

## Next milestone

**Module 5 — Execution / Orchestration.** The Temporal workflow per `PlaybookRun`:
runtime graph traversal driving `active_step_id` (using Module 4's `traversal`
rules), timing/fire-time computation (offset from previous completion, payday
substitution, `allowed_hours` deferral — D-025), guardrail checks immediately
before each action (retry budgets, quiet hours, pre-debit gap, systemic hold), the
atomic `Action` + `CaseEvent` write (the `write_action_and_event` primitive
already exists), and settling **U-02**'s `STEP_TRANSITIONED` payload. Do not start
without an approved scope.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`.
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** Routine mapping
   choices may be made and documented as decisions.
6. `state_machine.py` / `guards.py` are load-bearing. Changing either needs
   explicit approval + a shown diff. (Module 4 changed **neither**.)
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01** — edges 1–2 (`DETECTED/DIAGNOSING → CANCELLED`) — Module 7. Edge 3
  RESOLVED (M7c). `DIAGNOSING → SYSTEMIC_HOLD` residual: not needed by M3/M4.
- **U-02** — `STEP_TRANSITIONED` payload provisional; **Module 5** settles it.
  Module 4 writes no `STEP_TRANSITIONED` (run creation is status-neutral).
- **U-03** — Tier 1 vs Tier 3 MAC precedence is a stated default.
- **U-04** — systemic N / M / sustain numbers are placeholders.
- **U-07** — inbound half RESOLVED (Celery). `PlaybookRun`-execution / Temporal
  half stays open — **Module 5**.
- **U-08** — issuer / BIN / acquirer / route extraction; blocks `ISSUER_SPECIFIC`
  systemic detection and the §5.3 first-touch MAC lookup (D-083).
- **U-05 / U-06** — Part D items 1–4; `MacCodeRegistry` unseeded codes.

## Known contradictions / caveats

- **`README.md` is stale.** Trust `CURRENT_STATE.md` / the code.
- **The Module-4 run is uncommitted.** Every "verified fact" above (754 tests, the
  `torque.policy` package) reflects the working tree, not any commit.
- **No auto-dispatch anywhere yet:** Module 2→3 (D-080) and Module 3→4 (D-088)
  triggers are deferred to the orchestration layer. Each engine + task is ready and
  independently invocable; nothing enqueues the next stage automatically.
- **Module 4 = policy, not execution.** `activate_case` creates the `PlaybookRun`
  and provides the graph-reading rules; it fires no actions, advances no
  `active_step_id`, computes no fire times, builds no Temporal (all Module 5).
- **No-playbook / disabled cases escalate** (D-086) — fraud-suspected, UPI
  cap-exhausted, NACH clearing-pending, dispute-suspected, subscription
  card-expired reach `PLAYBOOK_ACTIVE` (≥ T) but have no catalog playbook, so
  Module 4 routes them `→ ESCALATED_TO_HUMAN`.
- **The catalog is app-seeded, not migrated** (D-085) — `seed_catalog(session)`
  must run at deploy/demo/test; it is idempotent.
- **`PLAYBOOK_ACTIVE → SYSTEMIC_HOLD`** legal but dormant (Module 5 drives it).
- Standing Module 2/3 caveats remain (Leg-3 rail seeding initial-state only;
  systemic rollup `payment.failed`-only; `NETWORK_WIDE`-only; subscription decline
  read from the source Event; checkout always escalates; etc.).

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py src/torque/models/guards.py`), report
any drift, then — once the maintainer has committed Module 4 — propose **Module 5 —
Execution / Orchestration** as one continuous scope per the module execution protocol.
