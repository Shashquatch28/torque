# CURRENT STATE — read this first

**Last updated:** 2026-09-04, after the **Module 7 — Payment Reconciliation &
Attribution** run (uncommitted, on top of committed Module 6 `9345ce9`).
**Reconstructed from:** committed Modules 1–6 (HEAD `9345ce9`) + the uncommitted
Module 7 changes + `Torque_Blueprint_v7_FullSystem.md`.
**This file is derived documentation, not authoritative.** The repo and blueprint win.

---

## What Torque is

A revenue-leakage recovery agent closing the loop across four funnel legs —
**payment degradation, checkout abandonment, subscription/mandate failure, B2B
receivables** — with **one shared case object and one shared event ledger**. It
diagnoses root cause, runs a bounded recovery playbook, executes it under hard
compliance guardrails, **reconciles incoming payments back to the case that was
leaking**, and measures incremental recovery against a held-out control. Full
vision: `PROJECT_CONTEXT.md` §1. Spec: `Torque_Blueprint_v7_FullSystem.md`.
Product-pitch knowledge base: `learning_log.md` (root).

## Where we are

**Modules 1–6 — COMPLETE & committed** (`9345ce9`). Signal ingestion → diagnosis
→ policy/playbook → execution → compliance/guardrail engine + Outreach Coordinator
+ human queue all live.

**Module 7 (Payment Reconciliation & Attribution) — §7 — COMPLETE** (this run,
**uncommitted**). New package `torque.reconciliation`.

| Module 7 capability | Behaviour |
|---|---|
| Entry point | `reconcile_event(session, *, event_id, now=None)` → `ReconcileOutcome`. Consumes a verified success `Event`; one transaction; idempotent on `Event.processed`; matched case rows `SELECT … FOR UPDATE`; tenant-scoped. |
| §7.1.1 direct | `payment_link.*` updates the `PaymentLink` row (`status`/`amount_paid`/`paid_at`). `paid`/`partially_paid` for a Torque link → its `case_id`, `AGENT_ASSISTED`. Unknown link + `notes.torque_case_id` → row created; otherwise → indirect. `expired`/`cancelled` → row status only (`LINK_UPDATED`). |
| §7.1.2 indirect | `payment.captured` / `subscription.charged`, one open case (`PLAYBOOK_ACTIVE` / `ESCALATED_TO_HUMAN`, or B2B `PARTIALLY_RECOVERED`) matching `(merchant_id, counterparty_id, amount)`. `AGENT_ASSISTED` iff a non-blocked `Action` (any `ActionCase`) executed within `PolicyConfig.attribution_window_hours` (24h), else `SELF_RECOVERED` (D-105). |
| §7.1.3 multi | Cases sharing one merged `Action`, or a set whose combined `amount_at_risk` a lump payment settles → re-split that `Action`'s `ActionCase.credit_weight` ∝ `amount_at_risk`, recover all (`AGENT_ASSISTED`, `MULTI_RECOVERED`). Non-merged multi-match → `AMBIGUOUS`, attribute to the latest-actioned case, leave the rest open (D-105). |
| §7.1.4 no-match | A `DETECTED` / `DIAGNOSING` case for `(merchant, cp, amount)` → customer self-paid before Torque acted → `CANCELLED` / `SELF_RECOVERED` (needs D-103). Else `NO_MATCH`. |
| §7.2 closure | Full → `RECOVERED`, `recovered_amount = amount_at_risk`, `closed_at`. B2B partial → invoices waterfalled oldest-`due_date`-first, `PARTIALLY_RECOVERED` (open), `amount_at_risk` ← `Σ outstanding` (INV-55). Final B2B settlement two-hops `PARTIALLY_RECOVERED → PLAYBOOK_ACTIVE → RECOVERED` (D-106). Every close: `PAYMENT_RECONCILED` `CaseEvent` + `human_queue.remove_for_case` (D-107). |
| Wiring | `torque.api.webhooks` dispatches `reconcile_event_task` for `payment.captured` / `subscription.charged` / `payment_link.*` after the `Event` write — no buffer (D-104). `celery_app` autodiscovers `torque.reconciliation`. |
| State machine | Module 7 added `DETECTED → CANCELLED` + `DIAGNOSING → CANCELLED` (D-103 — U-01 fully resolved). `guards.py` byte-unchanged. |

**Modules 8–13 not started.** The Module 7 run is **uncommitted**.

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`9345ce9`** (committed Module 6). Module 7 changes sit uncommitted on top. |
| Working tree | Module 7. Modified: `src/torque/state_machine.py` (**the two U-01 `→ CANCELLED` edges + docstring — D-103, reported before the edit**), `src/torque/api/webhooks.py` (reconcile dispatch), `src/torque/ingestion/celery_app.py` (autodiscover), `src/torque/ingestion/identity.py` (`find_counterparty`), `src/torque/coordination/human_queue.py` (`remove_for_case`), `tests/conftest.py` (`razorpay_payment_link_body` + reconcile spy), `tests/test_schema_introspection.py` / `tests/test_state_machine.py` (Module 7 assertions; 3 pre-existing state-machine tests inverted). New: `src/torque/reconciliation/` (4 files), 7 `tests/test_module7_*.py`. |
| Alembic head / current | **`0016_human_queue`** — **Module 7 added no migration** (all columns/enums/event types already existed). |
| Test suite | **900 passed** (`uv run pytest -q`), 0 fail / 0 skip. 1 cosmetic `StarletteDeprecationWarning` (pre-existing). |
| `def test_` functions | **772** (was 737) |
| Lint | `uv run ruff check .` → clean |
| Migration roundtrip | green (up→down→up incl. 0016) |
| `src/torque/models/guards.py` | **`git diff HEAD --` empty** — byte-unchanged. |
| `src/torque/state_machine.py` | **CHANGED** — `git diff HEAD --` = exactly `CANCELLED` added to `_TRANSITIONS[DETECTED]` + `_TRANSITIONS[DIAGNOSING]` and the docstring's "NOT YET ADDED" block replaced (D-103). Nothing else. |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI, Celery + Redis + beat, PostgreSQL 16, `uv`, pytest, ruff |
| DB / infra | Postgres host **5442**; Redis host **6389**. Tests run eager/mocked. **25 tables** (unchanged — Module 7 added none). |

## What is implemented (new in Module 7)

- **`torque.reconciliation`** package: `reconcile.py` (`reconcile_event`,
  `ReconcileOutcome`, `RECONCILE_EVENT_TYPES`, the §7.1 matcher + §7.2 closure),
  `payloads.py` (`payment_link.*` extractors), `tasks.py` (`reconcile_event_task`).
- **`state_machine.py`**: the two U-01 `→ CANCELLED` edges (D-103).
- **Helpers**: `ingestion.identity.find_counterparty` (match-only, no create);
  `coordination.human_queue.remove_for_case`.
- **Wiring**: `webhooks.py` reconcile dispatch (D-104).

Full breakdown: `ARCHITECTURE.md` §8G.

## Next milestone

**Module 8 — Recovery Scoring Model.** `probability = lookup(leg_type,
amount_bucket, days_since_failure)` (Decision F table) as a live function, then a
`promise_keeping_rate` warm-start multiplier capped 0.5×–1.3×; `cost` from
`ChannelRateCard` (next-likely-step channel sum); recompute on case creation /
diagnosis completion / daily. It **replaces the
`torque.coordination.outreach_coordinator.priority()` placeholder** through that
seam (D-098) — the Outreach Coordinator ordering and the human queue then sort by
the real `(probability × amount_at_risk) ÷ cost`. Do not start without an
approved scope.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`.
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** (Module 7 resolved
   U-01 #1/#2 — explicitly assigned to Module 7 by that file; the exact
   `state_machine.py` diff was reported before the edit.)
6. `state_machine.py` / `guards.py` are load-bearing. Changing either needs
   explicit approval + a shown diff. (Module 7 changed `state_machine.py` — the
   two U-01 edges, D-103; `guards.py` untouched.)
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01** — **FULLY RESOLVED.** Edge 3 (M7c, D-066); edges 1–2 (Module 7, D-103).
- **U-02** — RESOLVED (Module 5, D-091).
- **U-03** — Tier 1 vs Tier 3 MAC precedence — stated default. Open.
- **U-04** — systemic N / M / sustain numbers are placeholders. Open.
- **U-07** — RESOLVED (Module 5, D-090).
- **U-08** — issuer / BIN / acquirer / route extraction; blocks `ISSUER_SPECIFIC`
  systemic detection and the §5.3 first-touch MAC lookup (D-083).
- **U-05 / U-06** — Part D items; `MacCodeRegistry` unseeded codes.

## Known contradictions / caveats

- **`README.md` is stale.** Trust `CURRENT_STATE.md` / the code.
- **Module 7 is uncommitted** on top of committed Module 6 (`9345ce9`). Every
  "verified fact" above (900 tests) reflects the working tree.
- **`state_machine.py` changed in Module 7** — the two `DETECTED/DIAGNOSING →
  CANCELLED` edges (D-103). Reported before the edit; `git diff` shows only those.
- **Reconciliation does not need `Module 5`'s link execution** — the §7.1.1 direct
  path updates existing `PaymentLink` rows and creates one from a
  `notes.torque_case_id`; it lights up fully once Module 5's
  `GENERATE_PAYMENT_LINK` execution creates link rows (still deferred).
- **§7.1's implicit rules are filled by D-105 / D-106** — which case statuses are
  "open", the `AMBIGUOUS` multi-match tie-break (latest-actioned case), and the
  B2B `PARTIALLY_RECOVERED → PLAYBOOK_ACTIVE → RECOVERED` two-hop.
- **`WRITTEN_OFF`** is a human-only close (`ESCALATED_TO_HUMAN → WRITTEN_OFF`),
  Module 10. Module 7 drives `→ {RECOVERED, PARTIALLY_RECOVERED}` on a payment.
- **`priority()` is still a placeholder** (`amount_at_risk` desc) — Module 8
  replaces it (D-098). Module 7 consumes no score.
- **The executor is still a stub (§5.4).** Torque still fires no real messages or
  charges — safe by construction.
- **Execution is still not auto-triggered** (Module 2→3, 3→4, 4→5). Module 7's
  webhook→reconcile dispatch IS wired (D-104) because it is the last consumer and
  disturbs no downstream resting state.
- Module 1–6 caveats still stand.

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py src/torque/models/guards.py` —
expect the two D-103 edges on `state_machine.py`, empty on `guards.py`), report
any drift, then — once the maintainer has committed Module 7 — propose **Module 8
— Recovery Scoring Model** as one continuous scope, landing the real score
through the `priority()` seam.
