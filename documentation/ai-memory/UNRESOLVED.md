# UNRESOLVED QUESTIONS REGISTER

Open design questions that constrain or block specific future work. Distinct from
`DEFERRED.md` (which is *scoped-out work that is otherwise well-understood*) —
these are things where **the design itself is not settled**.

For each: **the question · current state in the repo · why it is unresolved ·
what it depends on · what would unblock it · whether implementation must stop
before it is resolved**.

When a question is answered: add a short "RESOLVED (date): …" note under it and,
if it produced a design decision, a `DECISIONS.md` entry. Do not delete it.

---

## U-01 — Three `RevenueLeakCase.status` state-machine edges are not defined

- **Question:** Should these transitions be legal, and with what
  trigger/guarding?
  1. `DETECTED → CANCELLED`
  2. `DIAGNOSING → CANCELLED`
  3. `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD`
- **Current state:** **Not in `state_machine.py`.** The module docstring lists
  them explicitly under "NOT YET ADDED — flagged, pending confirmation before the
  owning module is built". `assert_transition` will raise
  `IllegalTransitionError` for all three today.
- **Why unresolved:** Edges 1–2 are implied by Module 7 §7.1.4 (a payment
  arrives before diagnosis finishes → close as `CANCELLED` /
  `SELF_RECOVERED`); edge 3 is implied by Module 2 §2.5 (an outage wave sweeps
  *already-active* cases into hold — the §4 diagram only shows
  `DETECTED → SYSTEMIC_HOLD`). Neither is in the blueprint §4 diagram, so the
  Module-1 build did not invent them.
- **Depends on:** Module 7 (edges 1–2), Module 2 (edge 3).
- **What would unblock it:** the maintainer confirming the edges (and their
  triggers / whether a `CaseEvent` beyond `STATUS_CHANGED` is written) as part of
  the Module 2 / Module 7 proposal.
- **Must implementation stop first?** Yes for Module 2's systemic-sweep step and
  Module 7's pre-diagnosis self-pay path — those cannot be built without adding
  the edge(s), and adding an edge to `state_machine.py` requires explicit
  approval + a shown diff (D-011). Other parts of those modules can proceed.
- **Progress (2026-09-02, M7a):** M7a (webhook verify + `Event` ingest) was built
  without touching `state_machine.py` — it creates no cases. The maintainer
  confirmed edge 3 (`PLAYBOOK_ACTIVE → SYSTEMIC_HOLD`) is to be locked in the
  **M7c** proposal (systemic detection), where it is first needed, with the
  required diff. Edges 1–2 remain Module 7's.
- **Edge 3 — RESOLVED (2026-09-02, M7c).** `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` was
  added to `_TRANSITIONS[PLAYBOOK_ACTIVE]` in `state_machine.py` (approved; diff
  shown in the M7c verification report), plus the docstring's "NOT YET ADDED"
  list updated. It is a **legal but dormant** edge — `transition_case` executes
  it with the existing guard architecture (no `guards.py` change; trigger
  `"systemic_network_wide"`; `STATUS_CHANGED` emitted), but M7c produces no
  `PLAYBOOK_ACTIVE` case and no code path drives it. Resume stays
  `SYSTEMIC_HOLD → DIAGNOSING`; there is no `SYSTEMIC_HOLD → PLAYBOOK_ACTIVE`
  edge. See `DECISIONS.md` **D-066**. **Edges 1–2 (`DETECTED/DIAGNOSING →
  CANCELLED`) remain unresolved — Module 7.**
- **Residual (not tracked as a separate edge):** `DIAGNOSING → SYSTEMIC_HOLD` is
  not in the §4 diagram, not in this list, and was **not** added by M7c. If
  Module 3's `DIAGNOSING` cases must be sweepable by a systemic breach, that edge
  needs its own proposal.

## U-02 — `CaseEvent.STEP_TRANSITIONED` payload shape is provisional

- **Question:** Is `{ from_step_id?, to_step_id, edge_condition, outcome }` the
  final shape?
- **Current state:** Implemented as `StepTransitionedPayload` in
  `events/payloads.py`, explicitly commented `PROVISIONAL — Part E item 3. Shape
  not yet independently confirmed.`
- **Why unresolved:** Blueprint Part E item 3 — it is a proposed default, not
  confirmed. `STEP_TRANSITIONED` is only ever written by Module 5's playbook
  traversal, which does not exist yet, so nothing has exercised the shape.
- **Depends on:** Module 5 (execution / graph traversal).
- **What would unblock it:** Module 5's design settling what a step transition
  actually needs to record (e.g. timing, the node's `action_id`, retry counters).
- **Must implementation stop first?** No — but Module 5 should revise this schema
  deliberately (with a `DECISIONS.md` entry) rather than assume it is final.

## U-03 — Tier 1 vs Tier 3 MAC precedence

- **Question:** When a case receives both a `TIER_1_HARD_STOP` and a
  `TIER_3_INSTRUMENT_DEAD` code across attempts, which wins?
- **Current state:** Code uses `TIER_1_HARD_STOP (rank 4) > TIER_3_INSTRUMENT_DEAD
  (rank 3)` (`_TIER_RANK` in `guards.py`; mirrored in `state_machine.tier_rank`).
- **Why unresolved:** Blueprint §4 / Part E item 2 — "a stated default, not yet
  independently confirmed". The two tiers route to different downstream actions
  (stop all contact vs. request a new instrument), so the ordering matters.
- **Depends on:** empirical validation against real Mastercard MAC behaviour
  (also a Module 5 / Decision M concern).
- **What would unblock it:** confirmation from Mastercard MAC documentation or
  live acquirer behaviour.
- **Must implementation stop first?** No. The current ordering is a safe default
  (the more absolute "stop" wins). Revisit if Module 5 evidence contradicts it.

## U-04 — Systemic threshold numbers (N, M, sustain window)

- **Question:** What are the real per-scope values for `baseline_floor` (N),
  `absolute_floor` (M), and the sustain window minutes?
- **Current state:** `PolicyConfig` carries `systemic_spike_multiplier = 5.0`
  (from Decision J, considered correct) and
  `systemic_baseline_floor_per_min = 1.0`,
  `systemic_absolute_count_floor = 20`,
  `systemic_sustain_window_minutes = 10` — the last three are **invented
  placeholders** (the code comment says so; no blueprint figure exists).
- **Why unresolved:** Blueprint §3 / Decision J call N and M "per-scope config
  values" without giving numbers; the sustain window default (10) is stated but
  the floors are not.
- **Depends on:** Module 2 §2.5 build + real/synthetic failure-rate data.
- **What would unblock it:** tuning against demo synthetic data during Module 2.
- **Must implementation stop first?** No — but do not treat these three defaults
  as authoritative.
- **Progress (2026-09-02, M7c).** The §2.5 job (`NETWORK_WIDE` tier) is now built
  and **consumes** `systemic_baseline_floor_per_min` (N),
  `systemic_absolute_count_floor` (M), `systemic_sustain_window_minutes`, plus
  the M7c-added `systemic_detection_window_minutes = 10` / `systemic_baseline_days
  = 7` (both blueprint figures). **M7c did NOT empirically validate or retune N /
  M / sustain** — they remain configurable placeholders. Still unresolved.

## U-05 — Blueprint Part D open decisions (not answered in the repo)

- **D item 1 — checkout-abandonment ingestion:** real storefront SDK/pixel vs.
  synthetic injection. Repo has neither. Proposed default = synthetic injection.
  Blocks a real Leg-2 ingestion path; does not block Module 2's Razorpay paths.
- **D item 2 — backend language/framework:** never formally chosen in the
  blueprint. **In practice the repo is committed to Python** (SQLAlchemy,
  Pydantic, Alembic, pytest). Treat Python as decided-by-implementation; the
  Temporal SDK choice (Python) follows. Note this if the maintainer ever
  reconsiders.
- **D item 3 — build-window length:** unknown. Module 12's roadmap has no
  calendar dates. Does not block milestone work.
- **D item 4 — judging rubric:** unknown. Only matters for Module 13.
- **Must implementation stop first?** Only D item 1 blocks a specific path
  (real Leg-2 ingestion). The rest do not block schema/logic milestones.

## U-06 — `MacCodeRegistry` unseeded codes

- **Question:** The tier for every MAC code Razorpay's acquirers actually return
  (only 13 are seeded).
- **Current state:** `DEFERRED.md` covers the *work*; the *answer* (correct tier
  per code) is genuinely unknown and must be validated against live gateway
  output (Decision M / Part E item 1).
- **What would unblock it:** live acquirer data during Module 5 pre-production;
  the self-surfacing flagged-`CaseEvent` mechanism gives a real list to work
  from.
- **Must implementation stop first?** No. Unseeded → `None` → Module 5's safe
  `TIER_2` default (once built). Do **not** guess tiers into the seed.

## U-07 — Workflow engine for `PlaybookRun` execution (Module 5; Decision C / Part E item 8)

- **PARTIALLY RESOLVED (2026-09-02, M7b).** The question had two halves.
  - **Inbound / Module 2 delayed jobs — RESOLVED:** **Celery + Redis (broker
    only, no result backend)**. Implemented in M7b (`torque.ingestion.celery_app`)
    for the §2.3 self-recovery buffer; M7c's §2.5 systemic job will use a Celery
    beat schedule or a plain scheduler. Celery is the Python-native stand-in for
    the blueprint's Node-only "BullMQ" — see `DECISIONS.md` **D-057**.
  - **Durable multi-day `PlaybookRun` execution — STILL OPEN:** Temporal
    (OSS, self-hosted) vs. the Postgres-polling fallback (`scheduled_jobs` table
    + stratified 10s/60s pollers). Nothing built. Not needed until Module 5.
- **Current state:** `celery` + `redis` are `dependencies`; `torque.ingestion`
  runs the inbound buffer. No workflow engine, no `scheduled_jobs` table.
- **Depends on (remaining half):** team comfort standing up a self-hosted
  Temporal cluster in the build window (Part D item 3).
- **What would unblock it:** the maintainer picking Temporal or the polling
  fallback when Module 5 is proposed.
- **Must implementation stop first?** Not for M7c (Celery beat / scheduler
  covers the 60s systemic job). **Yes for Module 5** `PlaybookRun` execution.

## U-08 — Issuer / BIN / acquirer / route extraction (blocks `ISSUER_SPECIFIC` systemic detection)

- **Question:** To do per-issuer systemic detection (§2.5 "for each `issuer_code`
  seen"), Torque needs an issuer (or BIN / acquirer / route) value per failure.
  Which field, extracted from where, stored on which model?
- **Current state:** **Nothing.** `issuer_code` exists only on `SystemicEvent`
  and the `SYSTEMIC_HOLD_APPLIED` payload. No extractor reads it; no leg context
  has it; `RevenueLeakCase` has no issuer column; `Network` enum is
  `MASTERCARD | VISA` only. M7c ships `NETWORK_WIDE` only (D-065).
- **Why unresolved:** Razorpay `payment.failed` payloads *do* carry
  `payload.payment.entity.card.issuer` (4-letter bank code, cards) and `.bank`
  (netbanking); UPI has no clean issuer. Extracting it faithfully is a real
  modelling decision (a `RevenueLeakCase` column? a `PaymentDegradationContext`
  field? populated at M7b ingestion time?), not something to bolt on at
  detection time by parsing arbitrary JSON.
- **Depends on:** a schema/context decision + the owning milestone.
- **What would unblock it:** the maintainer choosing the field, its source, its
  model, and the milestone that adds it (likely a follow-on to Leg-1/Leg-3
  ingestion).
- **Must implementation stop first?** Only for `ISSUER_SPECIFIC` systemic
  detection. `NETWORK_WIDE` (M7c) and everything else proceed.

---

## Resolved (kept for history)

### U-01 #3 (`PLAYBOOK_ACTIVE → SYSTEMIC_HOLD`) — RESOLVED 2026-09-02 (M7c)

Added to `_TRANSITIONS[PLAYBOOK_ACTIVE]` in `state_machine.py` as a **legal but
dormant** edge (approved; diff shown in the M7c verification report). Executed by
`transition_case` with the existing guard architecture — no `guards.py` change,
trigger `"systemic_network_wide"`, `STATUS_CHANGED` emitted. M7c drives it from
no code path (it produces no `PLAYBOOK_ACTIVE` case); Module 5 owns driving it +
mid-run recovery. Resume is the existing `SYSTEMIC_HOLD → DIAGNOSING`. See
`DECISIONS.md` D-066. **U-01 edges 1–2 (`DETECTED/DIAGNOSING → CANCELLED`) stay
open — Module 7.**

### U-07 (inbound half) — RESOLVED 2026-09-02 (M7b)

Module 2's inbound delayed-job mechanism is **Celery + Redis (broker only, no
result backend)**. Celery replaces the blueprint's Node-only "BullMQ" for the
same high-throughput stateless inbound role; this is a scope/implementation
choice, not a reversal of the Temporal preference for `PlaybookRun`. See
`DECISIONS.md` D-057. The `PlaybookRun`-execution half of the original question
stays open above.
