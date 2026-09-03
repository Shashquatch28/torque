# CURRENT STATE — read this first

**Last updated:** 2026-09-04, after the **Module 6 — Compliance & Cross-Leg
Guardrail Engine** run (uncommitted, on top of committed Module 5 `e8194c2`).
**Reconstructed from:** committed Modules 1–5 (HEAD `e8194c2`) + the uncommitted
Module 6 changes + `Torque_Blueprint_v7_FullSystem.md`.
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

**Modules 1–4 — COMPLETE & committed** (`c17dd82`). **Module 5 (Execution &
Orchestration) — COMPLETE & committed** (`e8194c2` = the Module 5 run + its
post-audit corrective pass; both are now committed — the earlier snapshot's
"uncommitted" note was stale).

**Module 6 (Compliance & Cross-Leg Guardrail Engine) — §6 — COMPLETE** (this run,
**uncommitted**). New package `torque.coordination`.

| Module 6 capability | Behaviour |
|---|---|
| Facade (§6.2) | `GuardrailEngine.check(session, *, action_type, now, case\|case_id, run, node, params)` → the **four-way `GuardDecision`** (ALLOW/BLOCK/DEFER/AUTO_INSERT_PREDEBIT — intentional deviation from `{allow, block_reason?}`, D-097). Composes the existing Module 5 / compliance predicates; §5.2 sequence first-failure-wins. Retry path = `check_retry_guardrails` verbatim. |
| WhatsApp gate | gate #1 `whatsapp_opt_in` → `CONSENT_NOT_OBTAINED`; gate #2 approved **UTILITY** template (`approved_template_exists`, reused) → `TEMPLATE_NOT_APPROVED`; systemic-hold precedes both |
| Open conversation (Q-F) | `active_wa_conversation_expires_at > now` → **DEFER** past the window (not a hard block — no enum migration) + enqueue the case (`OPEN_WA_CONVERSATION`) |
| Cross-leg quiet period | 4h (`PolicyConfig.cross_leg_quiet_period_hours`) between outreach from *different* legs to the same counterparty → DEFER to `quiet_period_end + timing_offset`; writes an `ACTION_BLOCKED`/`OUTREACH_COORDINATOR_DEFERRED` row, step held (D-099) |
| Merge (Part A §5 / §4.4) | grouped in the poll batch (both jobs already claimed under one `SKIP LOCKED`); higher-`priority` case owns one `Action` + one `ActionCase` per case (Σ `credit_weight` == `Decimal("1.00000")`); no `multi_case_template` → primary sends single-case, each secondary defers, never dropped (D-102) |
| Priority | `outreach_coordinator.priority(case)` — the **Module 8 seam**; placeholder = `amount_at_risk` desc (D-098) |
| Escalation ceiling (§6.3) | `runner._escalation_ceiling_hit` / `_escalate_on_ceiling` — one check at the top of the tick; unsuccessful attempts (`BLOCKED`/`FAILED`/`NO_RESPONSE`) ≥ `escalation_ceiling` → case `ESCALATED_TO_HUMAN` (existing legal edge, trigger `"escalation_ceiling"`), run `ESCALATED`, enqueue, drop timer, `StepResult.ESCALATED_CEILING`. Short-circuits before a graph-terminal `ESCALATE_HUMAN`. `escalation_ceiling <= max_attempts` enforced at save time (D-100 / INV-51). |
| Human queue (§6.4) | `human_queue` table (migration **0016**), `TenantScoped`, `UNIQUE(case_id)` idempotent. Feeders: `sweep_escalated_to_human` (Q-H — no Module 3 change), escalation-ceiling (inline), `route_broken_promise` (routing hook — `LOG_PROMISE` still deferred). `list_for_merchant` orders priority-desc + FIFO, or `order="fifo"`. |

**Modules 7–13 not started.** The Module 6 run is **uncommitted**.

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`e8194c2`** (committed Module 5 + corrective pass). Module 6 changes sit uncommitted on top. |
| Working tree | Module 6. Modified: `src/torque/config.py` (+`cross_leg_quiet_period_hours`), `src/torque/execution/guardrails.py` (+2 optional `GuardDecision` fields), `src/torque/execution/runner.py` (facade dispatch, ceiling check, DEFER-writes-blocked-Action), `src/torque/execution/scheduler.py` (merge grouping in `execute_due_jobs`), `src/torque/models/__init__.py` (+`HumanQueueEntry`), `src/torque/playbooks/validation.py` (+`_check_escalation_ceiling`), `tests/conftest.py` (`whatsapp_opt_in=True` default + `make_active_run` seeds a WA template), `tests/test_module4_versioning.py` (coherent v2 rules), `tests/test_schema_introspection.py` (+5 Module 6 tests). New: `src/torque/coordination/` (5 files), `src/torque/models/human_queue_entry.py`, `migrations/versions/0016_human_queue.py`, 7 `tests/test_module6_*.py`. |
| Alembic head / current | **`0016_human_queue`** (Module 6 added it; additive — one table, no enum, no `CaseEventType`). |
| Test suite | **865 passed** (`uv run pytest -q`), 0 fail / 0 skip. 1 cosmetic `StarletteDeprecationWarning` (pre-existing). |
| `def test_` functions | **737** (was 689) |
| Lint | `uv run ruff check .` → clean |
| Migration roundtrip | green (up→down→up incl. 0016) |
| `src/torque/state_machine.py` | **`git diff HEAD --` empty** — byte-unchanged. §6.3 escalation uses the existing legal `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN` edge. |
| `src/torque/models/guards.py` | **`git diff HEAD --` empty** — byte-unchanged. |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI, Celery + Redis + beat, PostgreSQL 16, `uv`, pytest, ruff |
| DB / infra | Postgres host **5442**; Redis host **6389**. Tests run eager/mocked. **25 tables** (Module 6 added `human_queue`). |

## What is implemented (new in Module 6)

- **`torque.coordination`** package: `guardrail_engine.py` (`GuardrailEngine`
  facade), `outreach_coordinator.py` (priority seam, cross-leg quiet period,
  open-conversation, WhatsApp gate, ceiling tally), `human_queue.py`
  (`HumanQueueReason`, `enqueue`, `list_for_merchant`, the three feeders),
  `merge.py` (`merge_groups`, `execute_merged`).
- **`human_queue`** model + migration 0016. **`GuardDecision`** gains
  `defer_until` / `human_queue_reason`. **`StepResult`** gains `ESCALATED_CEILING`
  / `MERGED`. Playbook validation gains `escalation_ceiling <= max_attempts`.

Full breakdown: `ARCHITECTURE.md` §8F.

## Next milestone

**Module 7 — Payment Reconciliation & Attribution.** Match `payment.captured` /
`subscription.charged` / `payment_link.paid` to open cases; `AGENT_ASSISTED` vs
`SELF_RECOVERED` (24h window); multi-case `credit_weight` re-split; case closure
(`RECOVERED` / `PARTIALLY_RECOVERED`, `B2BInvoice.outstanding_amount` decrement) +
`PAYMENT_RECONCILED`; the `DETECTED/DIAGNOSING → CANCELLED` state-machine edges
(U-01 #1–2 — needs approval + a shown `state_machine.py` diff). Do not start
without an approved scope.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`.
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** (Module 6 resolved
   none — U-01/03/04/08 untouched.)
6. `state_machine.py` / `guards.py` are load-bearing. Changing either needs
   explicit approval + a shown diff. (Module 6 changed **neither**.)
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01** — edges 1–2 (`DETECTED/DIAGNOSING → CANCELLED`) — Module 7. Edge 3
  RESOLVED (M7c).
- **U-02** — **RESOLVED** (Module 5, D-091).
- **U-03** — Tier 1 vs Tier 3 MAC precedence — stated default. Open.
- **U-04** — systemic N / M / sustain numbers are placeholders. Open.
- **U-07** — **RESOLVED** (Module 5, D-090): durable execution = Postgres-polling.
- **U-08** — issuer / BIN / acquirer / route extraction; blocks `ISSUER_SPECIFIC`
  systemic detection and the §5.3 first-touch MAC lookup (D-083).
- **U-05 / U-06** — Part D items; `MacCodeRegistry` unseeded codes.

## Known contradictions / caveats

- **`README.md` is stale.** Trust `CURRENT_STATE.md` / the code.
- **Module 6 is uncommitted** on top of committed Module 5 (`e8194c2`). Every
  "verified fact" above (865 tests, migration 0016) reflects the working tree.
- **`GuardrailEngine.check()` returns the four-way `GuardDecision`**, not the
  blueprint's `{allow, block_reason?}` (D-097 / Q-A) — a documented deviation so
  Module 5's shipped DEFER / AUTO_INSERT_PREDEBIT semantics don't regress.
- **`priority()` is a placeholder** (`amount_at_risk` desc) — the real Module 8
  `(probability × amount) ÷ cost` replaces it through that one function (D-098).
- **The open-WhatsApp-conversation path is a DEFER + human-queue flag**, not a
  hard block — avoids a `BlockReason` enum migration (Q-F). `HumanQueueReason` has
  a 4th value `OPEN_WA_CONVERSATION` beyond §6.4's three feeders.
- **Cross-stratum merge is not attempted** — the 10 s / 60 s pollers claim
  disjoint job sets, so a merge pair split across them sends solo (the safe
  un-merged baseline, not a double-send; `UNIQUE(run_id)` + `SKIP LOCKED` still
  guarantee each step fires once). Documented in `merge.py` / D-102.
- **An `OUTREACH_COORDINATOR_DEFERRED` block counts toward the escalation
  ceiling** (it is a `BLOCKED_BY_GUARDRAIL` row) — a case that can never get an
  outreach through legitimately escalates to a human (D-100 / Q-D, literal).
- **The executor is still a stub (§5.4).** Module 6 fires no real messages —
  safe by construction. Real channel adapters remain deferred.
- **Execution is still not auto-triggered.** Module 4→5 dispatch (D-093) and the
  earlier inter-module triggers stay deferred; the demo/tests wire them.
- Module 1–5 caveats still stand.

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py src/torque/models/guards.py`), report
any drift, then — once the maintainer has committed Module 6 — propose **Module 7
— Payment Reconciliation & Attribution** as one continuous scope, surfacing the
U-01 `CANCELLED` edges as a question with the required `state_machine.py` diff.
