# DECISIONS LOG (ADR-style, APPEND-ONLY)

Every consequential design decision made while building Milestones 1–6b. This
file is **append-only**: never edit or delete a past entry. If a decision is
later reversed, add a new entry and mark the old one
`SUPERSEDED BY DECISION D-0NN` (leave everything else in the old entry intact).

**Authority:** each decision is the blueprint's unless the entry says
"intentional deviation". Where repo evidence does not establish the reasoning, it
is marked `REASONING: UNKNOWN (not establishable from repo)`.

Fields per entry: **Milestone · Decision · Chosen · Alternatives · Reasoning ·
Consequence · Status**.

Status legend: `IN FORCE` (current, immutable unless superseded) · `SUPERSEDED
BY D-0NN`.

---

## D-001 — Application-layer multi-tenancy via `TenantScope`
- **Milestone:** M1
- **Decision:** How is `merchant_id` isolation enforced for the demo build?
- **Chosen:** Every tenant-scoped table carries a non-null `merchant_id`; all
  access goes through `TenantScope` (`db/scoped.py`), which always injects
  `merchant_id` into reads and stamps it on writes. `Counterparty` and static
  config are deliberately exempt (see D-002). A flush guard (`_guard_case`) backs
  it for `RevenueLeakCase`.
- **Alternatives:** Postgres Row-Level Security now; a WHERE-clause discipline
  with no facade.
- **Reasoning:** Blueprint §2.1 / Decision B — RLS is defense-in-depth past demo
  data volumes; a single always-injecting query layer is sufficient and simpler
  for the demo. `.unscoped()` is an explicit, greppable escape hatch.
- **Consequence:** No query may bypass `TenantScope` for tenant models. RLS is
  roadmap (`DEFERRED`).
- **Status:** IN FORCE

## D-002 — `Counterparty` and static config are globally scoped
- **Milestone:** M1 (extended M2/M3/M4)
- **Decision:** Do identity and static-config tables carry `merchant_id`?
- **Chosen:** No. `Counterparty`, `MacCodeRegistry`, `ChannelRateCard`,
  `PlaybookIdentity`, `Playbook` are global. Relationship data is scoped via
  `Merchant_Counterparty`. (Resolved question "R3" in code comments.)
- **Alternatives:** Duplicate counterparties per merchant; scope the registry per merchant.
- **Reasoning:** A Mastercard code / channel rate means the same thing for every
  merchant; PII must exist once (D-003). Per-merchant relationship facts live on
  the join table.
- **Consequence:** `TenantScope.select()` raises `NonTenantModelError` for these;
  callers use `.unscoped()`.
- **Status:** IN FORCE

## D-003 — `Counterparty` is the single PII source; erasure = null-in-place
- **Milestone:** M1
- **Decision:** Where does raw PII live and how is DPDP erasure done?
- **Chosen:** `name` / `phone` / `email` only on `counterparty` (all nullable).
  `redact_pii()` nulls them and appends an `erased` entry to `consent_log`.
  Everything else references `counterparty_id`.
- **Alternatives:** PII copied onto cases/actions for convenience; a separate
  `pii_vault` table; hard-delete on erasure.
- **Reasoning:** Blueprint §2.2 — erasure must leave case/event history
  structurally intact while de-identifying.
- **Consequence:** No other table may store raw PII. Erasure-request intake UI
  and `Action.content_sent` redaction cascade are `DEFERRED` (Decision H).
- **Status:** IN FORCE

## D-004 — `consent_log` is JSONB on `Counterparty` (not a child table) for M1
- **Milestone:** M1
- **Decision:** Model `consent_log` as a column or a table?
- **Chosen:** JSONB list column (resolved question "R6").
- **Alternatives:** `counterparty_consent_event` child table now.
- **Reasoning:** Sufficient for the demo; promotable to a child table later with
  no change to the erasure model.
- **Consequence:** Consent-history queries are JSONB queries for now.
- **Status:** IN FORCE

## D-005 — `CaseEvent` is the only history mechanism; three fields eliminated
- **Milestone:** M1
- **Decision:** How is execution/audit history stored?
- **Chosen:** One append-only `case_event` table. `AuditLogEntry`,
  `PlaybookRun.step_history`, and `Action.merged_case_ids` are **eliminated, not
  deprecated** — never to be recreated (noted in `models/__init__.py` docstring).
- **Alternatives:** A generic audit-log table alongside domain events; a
  step-history JSON on the run.
- **Reasoning:** Blueprint §2.3 — one stream makes the "why did the agent do
  this" view a query, not a feature.
- **Consequence:** Every step transition, block, status change, etc. is a
  `CaseEvent` row. Multi-case actions use `ActionCase` (D-016), not an array.
- **Status:** IN FORCE

## D-006 — `CaseEvent` append-only, enforced two ways
- **Milestone:** M1
- **Decision:** How is immutability of the history stream guaranteed?
- **Chosen:** (a) Postgres trigger `case_event_no_mutate` (fn
  `torque_case_event_immutable`, migration `0005`) raising on UPDATE/DELETE;
  (b) `before_flush` guard rejecting dirty/deleted `CaseEvent` instances.
- **Alternatives:** Trigger only; ORM convention only; event-store product.
- **Reasoning:** The trigger stops raw SQL; the guard gives a fast, typed error
  through the ORM path and catches it before the DB round-trip.
- **Consequence:** No code path (ORM or SQL) can mutate a `CaseEvent`.
- **Status:** IN FORCE

## D-007 — 10 locked `CaseEvent.payload` schemas; no type without a schema
- **Milestone:** M1 (M5 touched `ACTION_EXECUTED`)
- **Decision:** How are event payloads validated?
- **Chosen:** Pydantic models (`extra="forbid"`) per `CaseEventType` in
  `events/payloads.py`; `validate_payload()` enforces; import-time assertion
  fails if the enum and the registry drift.
- **Alternatives:** Free-form JSON; JSON Schema files.
- **Reasoning:** Blueprint §4 — "No `event_type` may be written without a
  matching schema."
- **Consequence:** Adding a `CaseEventType` requires adding a payload model in
  the same change.
- **Status:** IN FORCE

## D-008 — `STEP_TRANSITIONED` payload shape is provisional
- **Milestone:** M1
- **Decision:** Lock the `STEP_TRANSITIONED` payload now?
- **Chosen:** Use the blueprint's proposed shape
  (`from_step_id?`, `to_step_id`, `edge_condition`, `outcome`) but mark it
  PROVISIONAL in the module docstring.
- **Alternatives:** Omit the schema until Module 5; lock it as final.
- **Reasoning:** Blueprint Part E item 3 — shape not independently confirmed.
- **Consequence:** Module 5 may revise it. Tracked in `UNRESOLVED.md` #2.
- **Status:** IN FORCE

## D-009 — `RevenueLeakCase.status` state machine: §4 diagram + Part C only
- **Milestone:** M1
- **Decision:** Which transitions are legal?
- **Chosen:** Exactly the §4 diagram, plus Part C item 1
  (`DIAGNOSING → ESCALATED_TO_HUMAN` direct), plus confirmed R4
  (`PARTIALLY_RECOVERED → PLAYBOOK_ACTIVE` legal **only** for
  `leg_type == B2B_RECEIVABLE`). Entry point `transition_case()` writes the
  `STATUS_CHANGED` `CaseEvent` atomically.
- **Alternatives:** A permissive machine; add Module 7/2 edges pre-emptively.
- **Reasoning:** Only transitions with a confirmed owner are added; the rest are
  flagged not guessed.
- **Consequence:** 3 edges (`DETECTED→CANCELLED`, `DIAGNOSING→CANCELLED`,
  `PLAYBOOK_ACTIVE→SYSTEMIC_HOLD`) are **not** in the machine — see D-010.
- **Status:** IN FORCE

## D-010 — Three state-machine edges deliberately withheld
- **Milestone:** M1
- **Decision:** Add the Module 2 / Module 7 edges now?
- **Chosen:** No. Documented in the `state_machine.py` docstring as "NOT YET
  ADDED — flagged, pending confirmation before the owning module is built".
- **Alternatives:** Add them speculatively.
- **Reasoning:** They are implied by later-module prose, not the §4 diagram; the
  owning module should lock them.
- **Consequence:** Module 2 (systemic sweep) and Module 7 (pre-diagnosis
  self-pay) must revisit `state_machine.py` with explicit approval. `UNRESOLVED.md` #1.
- **Status:** IN FORCE

## D-011 — `state_machine.py` scope boundary
- **Milestone:** M1 (reaffirmed M6a)
- **Decision:** What may `state_machine.py` touch?
- **Chosen:** `RevenueLeakCase.status` transitions + `apply_network_directive`
  + `sync_control_group` only. It does **not** touch `PlaybookRun.status`,
  `PromiseToPay.status`, or `PaymentLink.status`. `PromiseToPay`'s lifecycle got
  its **own** module (`torque.promises`, M6a) rather than being folded in.
- **Alternatives:** One mega state-machine module for all status columns.
- **Reasoning:** Keeps the load-bearing case machine small and stable; other
  lifecycles are simpler and independently owned.
- **Consequence:** `state_machine.py` has been byte-stable since **M1**
  (`git log` shows `abbab18` as its only commit). Any change needs approval + a
  shown diff.
- **Status:** IN FORCE

## D-012 — `network_directive` as two columns; most-restrictive-wins
- **Milestone:** M1
- **Decision:** Store `{mac_code, tier}` how, and how does it update?
- **Chosen:** Two discrete columns (`network_directive_mac_code`,
  `network_directive_tier`) — not a JSON blob — because every module checks the
  tier without a context parse. `apply_network_directive()` is the sole writer;
  rank `TIER_1(4) > TIER_3(3) > TIER_2(2) > TIMED_RETRY(1) > None(0)`; downgrade
  raises `MonotonicityViolation`. Guard also blocks writes outside
  `network_directive_writer(session)`.
- **Alternatives:** JSONB blob; allow free overwrite.
- **Reasoning:** Blueprint §3 / §4 — non-overridable most-restrictive tier ever
  received; per-attempt raw history stays in `CaseEvent`
  (`NETWORK_DIRECTIVE_RECEIVED`).
- **Consequence:** Tier 1 vs Tier 3 precedence is a stated default, not
  confirmed (`UNRESOLVED.md`, blueprint Part E item 2).
- **Status:** IN FORCE

## D-013 — `recovery_type` / `recovered_amount` are Module-7-only
- **Milestone:** M1
- **Decision:** Who may write the reconciliation fields on `RevenueLeakCase`?
- **Chosen:** Only code inside `guards.module7_writer(session)`; any other write
  raises `OwnershipViolation`.
- **Alternatives:** Convention ("Module 7 writes these").
- **Reasoning:** Ownership is an invariant, not a code-review note.
- **Consequence:** The context manager exists; no caller uses it yet (Module 7
  is `PLANNED`).
- **Status:** IN FORCE

## D-014 — `root_cause_code` is a plain string, not an enum in M1
- **Milestone:** M1
- **Decision:** Freeze the diagnosis vocabulary now?
- **Chosen:** No. `root_cause_code` / `root_cause_label` are `String` columns.
  The enum is owned by Module 3 §3.1.
- **Alternatives:** Define the enum in `enums.py` now.
- **Reasoning:** Blueprint — freezing it in Module 1 would create a false contract.
- **Consequence:** Module 3 introduces the enum + (likely) a CHECK or migration.
- **Status:** IN FORCE

## D-015 — `in_control_cohort` assigned exactly once
- **Milestone:** M1
- **Decision:** Can a counterparty's cohort change?
- **Chosen:** No. `MerchantCounterparty.assign_cohort()` raises
  `CohortAlreadyAssignedError` if `in_control_cohort is not None`. `NULL` = not
  yet assigned.
- **Alternatives:** Mutable cohort; per-case randomization.
- **Reasoning:** Blueprint §2.2 / §6 — fixes case-level randomization
  contamination; one cohort per merchant-relationship, persists across legs.
- **Consequence:** Incrementality unit is stable. Cross-merchant SUTVA exposure
  remains (Module 9 footnote, `PLANNED`).
- **Status:** IN FORCE

## D-016 — Three retry rails: three separate entities, none a template
- **Milestone:** M2
- **Decision:** Model card / UPI / NACH retry compliance how?
- **Chosen:** Three distinct tables (`card_retry_budget`, `upi_retry_budget`,
  `nach_retry_policy`) and three distinct pure predicates in
  `compliance/retry_rails.py`. No shared base class.
- **Alternatives:** One `retry_budget` table with a `rail` discriminator.
- **Reasoning:** Blueprint §2.6 — three structurally different enforcers (card
  network volume counter; NPCI hard cap + execution window; bank-discretionary
  FY dishonour threshold). Forcing a common shape would misrepresent them.
- **Consequence:** Each rail evolves independently.
- **Status:** IN FORCE

## D-017 — `UPIRetryBudget.hard_cap` locked at 3 by CHECK
- **Milestone:** M2
- **Decision:** Represent the NPCI 1+3 cap how?
- **Chosen:** Column `hard_cap` with `server_default text("3")` and
  `CHECK (hard_cap = 3)`. `UPI_AUTOPAY_HARD_CAP = 3` constant in
  `compliance/retry_rails.py`.
- **Alternatives:** A bare constant with no column; a merchant-configurable field.
- **Reasoning:** NPCI-enforced, not merchant-configurable — the DB should refuse
  any other value.
- **Consequence:** Playbook validation (D-022) also imports the same constant for
  defense-in-depth.
- **Status:** IN FORCE

## D-018 — `permitted_execution_window` is not a column
- **Milestone:** M2
- **Decision:** Store NPCI peak windows per row?
- **Chosen:** No. Module-level `UPI_PEAK_WINDOWS_IST` + `IST` constants and the
  pure predicate `within_upi_execution_window()`. Peak = closed intervals
  `10:00–13:00`, `17:00–21:30` IST.
- **Alternatives:** A `permitted_execution_window` column per budget row.
- **Reasoning:** It is a system-wide NPCI rule, not per-mandate data.
- **Consequence:** Timezone handling: aware datetimes → IST; naive assumed IST
  wall-clock.
- **Status:** IN FORCE

## D-019 — `mandate_id` is an indexed String, not a FK
- **Milestone:** M2
- **Decision:** Reference mandates how, in `upi_retry_budget` /
  `nach_retry_policy`?
- **Chosen:** Indexed `String(128)` external identifier — Torque has no internal
  `Mandate` entity.
- **Alternatives:** Introduce a `Mandate` table now.
- **Reasoning:** Nothing in Module 1 owns mandate lifecycle; a FK would be a
  dangling contract.
- **Consequence:** `UNIQUE(mandate_id, merchant_id)` gives per-mandate-per-merchant
  uniqueness without a FK.
- **Status:** IN FORCE

## D-020 — `MacCodeRegistry` seeds only the 13 locked rows
- **Milestone:** M2
- **Decision:** How much of the MAC table to seed?
- **Chosen:** Only `03, 21, 5C, 9G, 40, 41, 24–30` (migration `0006`). No Visa
  equivalents. `tier_for()` returns `None` on a miss and leaves the fallback to
  the caller.
- **Alternatives:** Seed a best-guess full table now.
- **Reasoning:** Blueprint Part E item 1 / Decision M — the rest must be
  validated against live acquirer output; the "unseeded → default TIER_2 + flag
  a CaseEvent" self-healing behaviour is Module 5.
- **Consequence:** Unseeded codes are `DEFERRED`; do not add rows speculatively.
- **Status:** IN FORCE

## D-021 — `Playbook` is global and strictly append-only, composite PK
- **Milestone:** M4
- **Decision:** Version playbooks how?
- **Chosen:** `playbook_identity` (slug PK, global) + `playbook` with **composite
  PK `(playbook_id, version)`**, `created_at` only (no `updated_at`). Every edit
  inserts `version + 1`. Enforced by trigger `playbook_no_mutate` (fn
  `torque_playbook_immutable`, `0009`) + flush guard. No mutable "latest" row.
- **Alternatives:** A mutable playbook row with a version integer; soft-delete.
- **Reasoning:** Blueprint §2.4 — a run pins its version and finishes on it.
  Mirrors `CaseEvent` immutability.
- **Consequence:** "Latest version" is a `MAX(version)` query. `PlaybookRun` uses
  a composite FK (D-023).
- **Status:** IN FORCE

## D-022 — Playbook validation runs in the flush guard, incl. UPI ≤3
- **Milestone:** M4
- **Decision:** Where is save-time playbook validation enforced?
- **Chosen:** `before_flush` guard calls `validate_playbook()` /
  `validate_merchant_playbook_config()` (from `torque.playbooks`), normalizing
  `steps_graph` / `stopping_rules` in place. Rules: entry names a node; edge
  endpoints exist; unique node ids; every non-terminal node has exactly one
  `on_success` + ≥1 fallback; **no cycles**; UPI AutoPay `max_attempts <= 3`
  (imports `UPI_AUTOPAY_HARD_CAP` from the compliance layer — defense-in-depth
  vs `UPIRetryBudget.hard_cap`).
- **Alternatives:** A caller-remembered `validate()` helper; DB-only checks.
- **Reasoning:** Blueprint §4.2 — "catch a bad playbook before it can ever run".
  Guard enforcement can't be forgotten.
- **Consequence:** A bad graph/rules dict cannot be flushed.
- **Status:** IN FORCE

## D-023 — `MerchantPlaybookConfig`: partial override, deep-merge vs latest version
- **Milestone:** M4
- **Decision:** How do merchants tune a global playbook?
- **Chosen:** Tenant-scoped row with a **partial** `stopping_rules_override`
  JSONB (nullable/`{}` = use base) + an `enabled` flag. Effective rules =
  `deep_merge(base, override)` then full `StoppingRules` validation. `deep_merge`:
  dict+dict recurse; scalar replace; **list replace wholesale**. Validated
  against the **latest** published `Playbook` version, including the UPI ceiling.
  `enabled` does **not** affect rule resolution (it's a Module 4 availability
  concern).
- **Alternatives:** Full override copy; merge against the run's pinned version.
- **Reasoning:** Blueprint §4.2 / decisions "A"/"2"/"6" in code — graph and
  template logic stay centrally authored.
- **Consequence:** `UNIQUE(merchant_id, playbook_id)`. FK to
  `playbook_identity`, so a config can never dangle.
- **Status:** IN FORCE

## D-024 — `PlaybookRun` pins its version via a composite FK
- **Milestone:** M4
- **Decision:** How does a run stay on its starting version?
- **Chosen:** `(playbook_id, playbook_version)` composite `ForeignKeyConstraint`
  → `playbook(playbook_id, version)`. Tenant-scoped (decision "G") even though
  templates are global.
- **Alternatives:** Store only `playbook_id` and resolve version at read time.
- **Reasoning:** Blueprint §2.4 — inserting a newer version must not alter an
  in-flight run.
- **Consequence:** `active_step_id` is a single nullable pointer, **not a log**
  (no `step_history` — D-005).
- **Status:** IN FORCE

## D-025 — `step_timing_semantics` / `trigger_condition` are not structured columns
- **Milestone:** M4
- **Decision:** Model these `Playbook` fields how?
- **Chosen:** `step_timing_semantics` is **not a column** (decision "K") — it is
  a fixed system-wide interpretation rule Module 5 implements. `trigger_condition`
  is freeform JSONB (decision "H").
- **Alternatives:** Structured columns / typed models now.
- **Reasoning:** Structure belongs to later diagnosis/runtime; premature typing
  would be a false contract.
- **Status:** IN FORCE

## D-026 — Every `Action` has ≥1 `ActionCase` row (universal attribution)
- **Milestone:** M5
- **Decision:** How is single-case vs multi-case attribution modelled?
- **Chosen:** **Intentional deviation.** The blueprint frames `ActionCase` as
  multi-case-only. Torque makes it universal: a single-case `Action` gets exactly
  one `ActionCase` (`is_primary=True`, `credit_weight=Decimal("1.00000")`). No
  implicit "no rows → 100% primary_case_id" fallback.
- **Alternatives:** Blueprint's framing (rows only when >1 case).
- **Reasoning:** Every downstream consumer — especially Module 7 — then uses one
  query: `SELECT case_id, credit_weight FROM action_case WHERE action_id = :id`.
- **Consequence:** `write_action_and_event()` always creates the row(s); the
  guard requires the complete set in the same flush.
- **Status:** IN FORCE

## D-027 — `Action.run_id` is nullable
- **Milestone:** M5
- **Decision:** Must every Action belong to a `PlaybookRun`?
- **Chosen:** No. `run_id` FK is nullable — `NULL` = system-level / human-override
  activity not tied to a run (e.g. a `SYSTEMIC_HOLD` action before any run exists).
- **Alternatives:** Require a run; synthesize a placeholder run.
- **Reasoning:** Some actions genuinely precede or sit outside a playbook run.
- **Status:** IN FORCE

## D-028 — `credit_weight` uses exact `Decimal`, `Numeric(6,5)`, sum == 1.00000
- **Milestone:** M5
- **Decision:** Numeric type and equality for attribution weights?
- **Chosen:** Column `Numeric(6,5)`; guard sums `Decimal(str(w))` and requires
  `== Decimal("1")` exactly (writer builds rows at `Decimal("1.00000")`). Never
  float. CHECK `credit_weight ∈ [0,1]`.
- **Alternatives:** `Float`; tolerance-based comparison (`abs(sum-1) < eps`).
- **Reasoning:** Blueprint §3 — "sum must equal exactly 1". Float can't promise that.
- **Consequence:** Multi-case splits must be chosen so the Decimals sum exactly.
- **Status:** IN FORCE

## D-029 — Action↔CaseEvent correlation is a payload string, not a column/FK
- **Milestone:** M5
- **Decision:** How are an `Action` and its `CaseEvent` linked?
- **Chosen:** The `CaseEvent` payload carries `action_id` as a **string**.
  `CaseEvent` gains **no `action_id` column and no FK** to `action`.
- **Alternatives:** A nullable `case_event.action_id` FK column.
- **Reasoning:** Keeps `CaseEvent` a pure typed-payload log; the correlation
  value lives where the payload schema already validates it.
- **Consequence:** The atomicity guard (D-030) matches on
  `payload["action_id"] == str(action.action_id)`.
- **Status:** IN FORCE

## D-030 — Action↔CaseEvent atomicity is a structural invariant
- **Milestone:** M5
- **Decision:** Enforce "no `Action` without its `CaseEvent` in one transaction"
  how?
- **Chosen:** **Intentional deviation.** Blueprint §2.3 calls this "a Module 5
  code-review checklist item". Torque promotes it to a `before_flush` guard: a
  new `Action` must be accompanied in the same flush by a new `CaseEvent` for
  `Action.primary_case_id` whose type matches the outcome (`ACTION_BLOCKED` iff
  `BLOCKED_BY_GUARDRAIL`, else `ACTION_EXECUTED`) and whose `payload.action_id`
  equals the Action's id. `write_action_and_event()` is the sanctioned path.
- **Alternatives:** Code review only; a transactional-outbox worker.
- **Reasoning:** Audit integrity is critical; code review is not an invariant.
  Both tables are in the same Postgres instance — one transaction suffices.
- **Consequence:** A bare `session.add(action)` without the event raises
  `ActionAtomicityError`.
- **Status:** IN FORCE

## D-031 — `ACTION_EXECUTED` payload: `channel` and `cost` nullable
- **Milestone:** M5
- **Decision:** Are `channel` / `cost` required on the executed-action event?
- **Chosen:** **Intentional deviation.** Both nullable. Cost computation is
  deferred; some action types (e.g. `RETRY_PAYMENT`) have no messaging channel.
- **Alternatives:** Require both (blueprint's payload table lists them plainly).
- **Reasoning:** Pricing (`ChannelRateCard` consumption) is Module 5/8; forcing a
  value now would fabricate data.
- **Consequence:** `Action.cost` column is likewise nullable.
- **Status:** IN FORCE

## D-032 — Added coherence CHECK constraints on `action`
- **Milestone:** M5
- **Decision:** Enforce outcome/field coherence how?
- **Chosen:** **Intentional addition** (beyond the blueprint text). CHECKs:
  `(outcome = 'BLOCKED_BY_GUARDRAIL') = (block_reason IS NOT NULL)` and
  `= (executed_at IS NULL)`; `cost IS NULL OR cost >= 0`. Same
  enum/detail-field pattern as `card_retry_budget.hard_stop_reason_coherent`.
- **Alternatives:** Application checks only.
- **Reasoning:** These are cheap biconditionals Postgres can express; make
  illegal states unrepresentable.
- **Status:** IN FORCE

## D-033 — `PaymentLink.action_id` is nullable
- **Milestone:** M6a
- **Decision:** Must every `PaymentLink` reference a Torque `Action`?
- **Chosen:** No — labelled "decision D10" in the M6a proposal/code (an internal
  milestone decision id, **not** a blueprint Part D item). Module 2 ingests
  `payment_link.*` webhooks broadly, including links created outside Torque. An
  unattributed link has `action_id = NULL`; Torque does **not** invent a
  synthetic `Action`.
- **Alternatives:** Require `action_id`; fabricate an Action per external link.
- **Reasoning:** Module 7 can still distinguish Torque-attributed recovery from
  `SELF_RECOVERED` / `AMBIGUOUS` without a fake row.
- **Consequence:** `case_id` stays non-null; `action_id` FK is nullable + indexed.
- **Status:** IN FORCE

## D-034 — `PaymentLink` paid⇔paid_at biconditional CHECK
- **Milestone:** M6a
- **Decision:** Encode the paid/timestamp coherence how?
- **Chosen:** `CHECK ((status = 'paid') = (paid_at IS NOT NULL))` — biconditional
  in **both** directions (name `paid_status_matches_paid_at`). Plus
  `amount_paid >= 0`.
- **Alternatives:** One-directional CHECK; app-only.
- **Reasoning:** Same pattern as `action.executed_at_matches_outcome`; prevents a
  `paid` row with no timestamp *and* a timestamped row not marked paid.
- **Note:** `partially_paid` intentionally does **not** require `paid_at`.
- **Status:** IN FORCE

## D-035 — `PaymentLinkStatus` bound by value via `values_callable`
- **Milestone:** M6a
- **Decision:** Handle the enum whose member names ≠ values?
- **Chosen:** `PaymentLinkStatus` members are `ISSUED="issued"` etc. The PG type
  (created in `0001`) uses the lowercase **values**, so the column passes
  `values_callable=lambda e: [m.value for m in e]` and `server_default
  text("'issued'")`.
- **Alternatives:** Rename members to match values; store as plain String.
- **Reasoning:** Blueprint §4 writes the values in Razorpay's lowercase casing;
  the Python member names stay uppercase for code style.
- **Consequence:** Any future column binding this enum must use the same
  `values_callable`.
- **Status:** IN FORCE

## D-036 — `PromiseToPay`: surrogate PK + `UNIQUE(captured_via)`
- **Milestone:** M6a
- **Decision:** Primary key for `promise_to_pay`?
- **Chosen:** Surrogate UUID `promise_id` PK **plus** a named
  `UNIQUE(captured_via)` constraint (`uq_promise_to_pay_captured_via`) to enforce
  the diagram's 0..1-promise-per-`Action` relationship.
- **Alternatives:** Make `captured_via` the PK; make `case_id` the PK.
- **Reasoning:** A stable surrogate id is friendlier for later references; the
  UNIQUE captures the real constraint without overloading the PK.
- **Status:** IN FORCE

## D-037 — `PromiseToPay.status` lifecycle: own module + guard, no CaseEvent
- **Milestone:** M6a
- **Decision:** Where does the promise lifecycle live and does it emit history?
- **Chosen:** A dedicated `torque.promises` module (`PROMISE_TRANSITIONS`,
  `assert_promise_transition`, `transition_promise`) **plus** an independent
  `before_flush` guard branch (`_guard_promise_to_pay`). Graph:
  `PENDING → {KEPT, BROKEN}`, both terminal; a new row must be `PENDING`
  (pre-flush `None` counts as `PENDING`). **No `CaseEvent` is written on a status
  change** — `PROMISE_CAPTURED` is the capture-time event and a Module 5 concern.
- **Alternatives:** Fold into `state_machine.py`; emit a `CaseEvent` on
  KEPT/BROKEN.
- **Reasoning:** D-011 keeps `state_machine.py` case-only; the promise graph is
  small and independent. History for kept/broken is a reconciliation concern, not
  yet owned.
- **Status:** IN FORCE

## D-038 — No `on_broken` column on `PromiseToPay`
- **Milestone:** M6a
- **Decision:** Persist the broken-promise routing target per row?
- **Chosen:** No — labelled "decision D4" in the M6a proposal/code (an internal
  milestone decision id, **not** a blueprint Part D item). A `BROKEN` promise
  routes to the human queue — Module 6 **runtime** behaviour, not per-row
  configuration.
- **Alternatives:** An `on_broken` enum/string column.
- **Reasoning:** Routing policy is uniform ("never a harsher automated message");
  storing it per row invites drift.
- **Status:** IN FORCE

## D-039 — `MerchantWhatsAppTemplate` is tenant-scoped
- **Milestone:** M6b
- **Decision:** Scope the WABA template table per merchant?
- **Chosen:** Yes — `TenantScoped`, `merchant_id` FK, not null, indexed.
- **Alternatives:** Global (like `MacCodeRegistry`).
- **Reasoning:** Template approvals are Meta-account-specific and belong to one
  merchant; the gate query is always `WHERE merchant_id = ...`.
- **Status:** IN FORCE

## D-040 — `WhatsAppTemplateCategory` enum = `UTILITY | MARKETING` only
- **Milestone:** M6b
- **Decision:** Which Meta categories to model?
- **Chosen:** A real PG enum `whatsapp_template_category` with exactly `UTILITY`,
  `MARKETING`. Created in migration **`0012`** (not `0001`).
- **Alternatives:** Include `AUTHENTICATION`; use a free string.
- **Reasoning:** Blueprint §3 mentions "utility/marketing". `category` is a
  closed, Torque-relevant vocabulary — an enum is right.
- **Consequence:** See D-041.
- **Status:** IN FORCE

## D-041 — `AUTHENTICATION` category deliberately excluded
- **Milestone:** M6b
- **Decision:** Support OTP/auth templates now?
- **Chosen:** No. Adding it later requires an explicit
  `ALTER TYPE whatsapp_template_category ADD VALUE 'AUTHENTICATION'` migration.
- **Alternatives:** Add it now "just in case".
- **Reasoning:** Torque has no auth-template use case; an unused enum value is a
  false signal that the flow is supported.
- **Consequence:** Tracked in `DEFERRED.md`.
- **Status:** IN FORCE

## D-042 — `approval_status` is a plain `String(32)`, no enum, no CHECK
- **Milestone:** M6b
- **Decision:** Model the Meta approval status how?
- **Chosen:** **Intentional "Meta vocabulary gap".** Plain `String(32)`, no PG
  enum, no CHECK. Meta owns and evolves this vocabulary (`APPROVED`, `PENDING`,
  `REJECTED`, `PAUSED`, `DISABLED`, `IN_APPEAL`, `LIMIT_EXCEEDED`, …). Meta's
  value is stored verbatim.
- **Alternatives:** A PG enum of known statuses; a CHECK constraining values.
- **Reasoning:** An enum/CHECK would break on the first status Meta adds and
  would need a migration per Meta change. The invariant is not "must be a known
  value" — it is D-043.
- **Consequence:** Real Meta integration can persist any status without a schema
  change.
- **Status:** IN FORCE

## D-043 — WhatsApp gate #2 passes only on exact `== "APPROVED"` (fail-closed)
- **Milestone:** M6b
- **Decision:** Semantics of the template-approval gate?
- **Chosen:** `WHATSAPP_APPROVED = "APPROVED"` is the single source of truth.
  `approved_template_exists()` passes **iff** a matching row has
  `approval_status == WHATSAPP_APPROVED` (exact, case-sensitive). Every other
  value — including `"approved"`, `PENDING`, and any future Meta status — fails
  the gate. Non-approved statuses are **not** enumerated.
- **Alternatives:** Case-insensitive match; a whitelist of "ok" statuses; a
  blacklist of "bad" ones.
- **Reasoning:** Fail-closed is the safe default for a compliance gate; a
  blacklist silently admits anything new.
- **Consequence:** Module 6 combines this with `whatsapp_opt_in` (gate #1) and
  the open-conversation check.
- **Status:** IN FORCE

## D-044 — WhatsApp gate index is `(merchant_id, leg_type, category)` — 3 columns
- **Milestone:** M6b
- **Decision:** Index the gate lookup how?
- **Chosen:** `Index("ix_merchant_whatsapp_template_gate", "merchant_id",
  "leg_type", "category")`. `approval_status` is **deliberately excluded** from
  the index.
- **Alternatives:** Add `approval_status` as a 4th column; a partial index
  `WHERE approval_status = 'APPROVED'`.
- **Reasoning:** The three-column prefix matches the gate's `WHERE` selectivity;
  `approval_status` is low-cardinality and checked as an equality filter after.
  Keeping it out avoids index churn on every Meta status change.
- **Status:** IN FORCE

## D-045 — No uniqueness on `merchant_whatsapp_template` beyond the PK
- **Milestone:** M6b
- **Decision:** Constrain `(merchant_id, leg_type, category)` to one row?
- **Chosen:** No. Only `template_id` PK is unique. Multiple `APPROVED` templates
  for the same `(merchant, leg, category)` may coexist.
- **Alternatives:** `UNIQUE(merchant_id, leg_type, category)`.
- **Reasoning:** A merchant legitimately has several approved templates per
  category/leg (variants); the gate only needs "≥1 approved exists".
- **Status:** IN FORCE

## D-046 — `ChannelRateCard.channel` / `MerchantPlaybookConfig` etc.: freeform channel, no channel enum
- **Milestone:** M3 (and reused)
- **Decision:** Model "channel" as an enum?
- **Chosen:** No. `channel` is a freeform `String` PK on `channel_rate_card`
  (seeded `whatsapp`, `email`, `sms`); `Action.channel` is a nullable `String`.
- **Alternatives:** A `Channel` enum.
- **Reasoning:** Channel set may grow (voice, RCS, …) and the value is a
  lookup key, not a branching discriminator in Module 1.
- **Status:** IN FORCE

## D-047 — `SystemicEvent` is tenant-scoped; coherence CHECK on scope
- **Milestone:** M3
- **Decision:** Scope systemic events per merchant? Constrain scope/target?
- **Chosen:** `TenantScoped` (thresholds/baselines are "the merchant's own"
  aggregate). CHECK `issuer_specific_names_a_target`:
  `scope = 'NETWORK_WIDE' OR issuer_code IS NOT NULL OR network IS NOT NULL`.
- **Alternatives:** Global systemic events; no coherence CHECK.
- **Reasoning:** Blueprint §3 — per-merchant baselines; an `ISSUER_SPECIFIC`
  event must name its target, a `NETWORK_WIDE` one need not.
- **Status:** IN FORCE

## D-048 — Systemic detection is predicates-only; numeric N/M are placeholders
- **Milestone:** M3
- **Decision:** How much of systemic detection to build?
- **Chosen:** Only the two pure predicates
  (`systemic_threshold_breached`, `systemic_resolved`). The 60-second job,
  failure-rate rollups, rolling baseline, `SYSTEMIC_HOLD` transitions, and batch
  re-queue are Module 2. `PolicyConfig` carries `systemic_spike_multiplier=5.0`
  (Decision J) but `systemic_baseline_floor_per_min`,
  `systemic_absolute_count_floor`, `systemic_sustain_window_minutes` defaults are
  **unverified placeholders** (no blueprint figure).
- **Reasoning:** Blueprint §2.5 owns detection; N/M are "per-scope config
  values", numbers TBD.
- **Consequence:** Tracked in `DEFERRED.md` / `UNRESOLVED.md`.
- **Status:** IN FORCE

## D-049 — `razorpay_signature` is a pure helper; the endpoint is Module 2
- **Milestone:** M1
- **Decision:** How much webhook handling in Module 1?
- **Chosen:** Only `compute_razorpay_signature` / `verify_razorpay_signature`
  (HMAC-SHA256 over raw bytes, constant-time, caller picks Live/Test secret).
  The HTTP endpoint that reads the raw body, verifies before parsing, and drops
  failures silently is Module 2.
- **Reasoning:** Blueprint §2.5 / Decision L is a cross-cutting Module 1
  requirement for the *helper*; the route is Module 2.
- **Status:** IN FORCE

## D-050 — Policy values centralized in `config.PolicyConfig` (unused in M1)
- **Milestone:** M1 (extended each milestone)
- **Decision:** Where do tunable windows/thresholds live?
- **Chosen:** `torque.config.PolicyConfig` (pydantic-settings, `TORQUE_POLICY_`
  prefix). Declared even when unused so later modules read fields instead of
  embedding literals. `PRE_DEBIT_MIN_GAP_HOURS = 24` is the exception — a legal
  floor, kept as a module constant in `compliance/pre_debit.py`, not a tunable.
- **Reasoning:** Blueprint Decision E / Part E items 9–12 — these are policy
  values, not literals.
- **Status:** IN FORCE

## D-051 — Razorpay webhook routing: per-merchant path segment
- **Milestone:** M7a
- **Decision:** How does an inbound Razorpay webhook map to a `merchant_id` (for
  `Event.merchant_id`, a NOT-NULL FK)?
- **Chosen:** `POST /webhooks/razorpay/{merchant_id}`. The merchant is named in
  the URL path. An unknown `{merchant_id}` → HTTP 200, silent drop, no row.
- **Alternatives:** (a) single-merchant demo constant; (c) resolve
  `payload.account_id` against a stored mapping; (d) add
  `merchant.razorpay_account_id` + lookup.
- **Reasoning:** Real Razorpay webhooks are configured per merchant account in
  *that merchant's* dashboard and post to whatever URL the merchant set — there
  is no partner multiplexer in this system. The path segment matches Razorpay's
  actual model and is not a shim to rip out later. (c)/(d) solve an
  aggregator-only problem Torque does not have.
- **Consequence:** No schema change for routing. `Event` writes are keyed off the
  path param via `TenantScope` (D-054).
- **Status:** IN FORCE

## D-052 — Live vs Test webhook secret chosen by per-deployment config, never both
- **Milestone:** M7a
- **Decision:** Blueprint §2.2 says "select the secret by the mode the request
  arrived on, never cross them" — but the mode is not reliably in the body. How
  is it selected?
- **Chosen:** `Settings.razorpay_webhook_mode: Literal["live","test"]`
  (env `RAZORPAY_WEBHOOK_MODE`, default `"test"`) — a per-deployment setting.
  `Settings.active_razorpay_webhook_secret()` returns exactly one of the existing
  global `razorpay_webhook_secret_live` / `_test`; `None` if that one is unset →
  the endpoint fails closed (drops every request). **The endpoint never tries the
  other secret.**
- **Alternatives:** Separate `/live` + `/test` route suffixes; a mode header;
  try-both.
- **Reasoning:** Try-both silently widens "valid Razorpay signature" to "matches
  either secret" — worse than either alternative. For a single-merchant demo a
  deployment is unambiguously one mode; a config value is simpler than a route
  suffix and avoids a redundant runtime branch.
- **Consequence:** Per-merchant webhook-secret storage is deferred (`DEFERRED.md`)
  — there is only one merchant to hold secrets for. M7a reuses the two global
  `Settings` fields declared back in M1.
- **Status:** IN FORCE

## D-053 — `event` composite index added in M7a, not deferred to M7c
- **Milestone:** M7a
- **Decision:** Add `ix_event_merchant_type_received_at`
  `(merchant_id, type, received_at)` now, or with the systemic-detection
  sub-milestone that first queries it?
- **Chosen:** Now — migration `0013` (M7a's only schema change; no table/column/
  enum). The existing single-column `ix_event_merchant_id` (from `0003`) is only
  a prefix of the access pattern Module 2 §2.4 (cross-leg dedup) and §2.5
  (systemic detection) need: a merchant's events of one `type` in a trailing
  window.
- **Alternatives:** Keep M7a zero-migration; add the index in M7c.
- **Reasoning:** The index is additive, non-breaking, and its need is named
  explicitly in the blueprint — not speculative. Splitting a second index
  migration onto the same table later is pure churn.
- **Consequence:** M7b/M7c inherit the index. The M7a webhook endpoint itself
  does not use it (it dedups on `UNIQUE(idempotency_key)`).
- **Status:** IN FORCE

## D-054 — Ingestion writes go through `TenantScope`, never `.unscoped()`
- **Milestone:** M7a
- **Decision:** The webhook handler knows `merchant_id` from the path — write the
  `Event` via `TenantScope(session, merchant_id).add(...)`, or via the raw
  session with an explicit `merchant_id` stamp (`.unscoped()`)?
- **Chosen:** `TenantScope`. The first real HTTP-facing write path in the system
  keeps the tenancy guarantee (INV-01) with no exception.
- **Alternatives:** `.unscoped()` with a manual stamp ("it's server-side").
- **Reasoning:** `merchant_id` is already in hand, so scoping costs nothing here —
  there is no friction `.unscoped()` would relieve. An ingestion bypass "just
  this once" is a precedent the next contributor cites for theirs.
- **Consequence:** `TenantScope.add` stamps `merchant_id`; the flush proceeds
  unguarded beyond that (`Event` is not in any `_before_flush` branch).
- **Status:** IN FORCE

## D-055 — Webhook endpoint response contract: always empty HTTP 200
- **Milestone:** M7a
- **Decision:** What does the endpoint return, and what does it persist, in each
  outcome?
- **Chosen:** **Every** outcome — accepted, duplicate, or silently dropped —
  returns an empty `200` (Razorpay only inspects the status code; 200 avoids its
  retry-on-failure). Persists exactly one `Event` row **only** for a request that
  is signature-verified **and** JSON-object-shaped **and** carries a non-empty
  `X-Razorpay-Event-Id` **and** names a known merchant **and** is not a duplicate.
  A verified body with no top-level `event` field is persisted with
  `type = "unknown"` (the table is "the raw inbound signal log" — a verified
  signal is never dropped for being unrecognized). A concurrent-insert
  `IntegrityError` on flush is caught and treated as a duplicate (200).
- **Alternatives:** `{"status": ...}` JSON bodies; 4xx on bad signature; drop
  unrecognized `event` types with no row.
- **Reasoning:** Matches §2.2 verbatim; keeps the endpoint a pure sink with one
  observable (the status code) and one side effect (at most one `Event`).
- **Status:** IN FORCE

## D-056 — `Event.processed` stays `False` through M7a
- **Milestone:** M7a
- **Decision:** Does M7a ever set `Event.processed = True`?
- **Chosen:** No. M7a writes `processed=False` and nothing flips it. The buffer /
  dispatch that would (§2.3, §2.7) is M7b.
- **Alternatives:** Mark `processed=True` immediately (there is no consumer, so it
  would be a lie); add a stub consumer.
- **Reasoning:** Honest reflection of what M7a does. `processed` becomes
  meaningful when M7b's dispatch exists.
- **Status:** SUPERSEDED BY D-063

## D-057 — Celery + Redis (broker only) for the Module 2 inbound buffer
- **Milestone:** M7b
- **Decision:** What runs the §2.3 self-recovery delayed job?
- **Chosen:** **Celery**, with **Redis as broker only** — no result backend.
  Postgres is the source of truth for every ingestion outcome. Worker run in dev
  with `celery -A torque.ingestion.celery_app:celery_app worker`;
  `Settings.celery_task_always_eager` (test harness only) runs tasks inline.
- **Alternatives:** BullMQ + Redis (blueprint Decision C's literal wording);
  a Postgres-polling job table.
- **Reasoning:** **Intentional implementation deviation.** BullMQ is a Node.js
  library — not usable from this Python codebase. Celery is the Python-native
  equivalent for the same inbound, high-throughput, stateless delayed-job role
  Decision C assigns to "BullMQ + Redis". This is a scope/implementation choice,
  **not** a reversal of the Temporal preference: Temporal (or the
  Postgres-polling fallback) for durable multi-day `PlaybookRun` execution
  remains a separate, still-open Module 5 decision (U-07 half / Part E item 8).
- **Consequence:** `celery`, `redis` added to `dependencies`. `torque.ingestion`
  package. No result backend, no `docker-compose` worker service (dev command +
  eager mode only).
- **Status:** IN FORCE

## D-058 — `is_hard_decline` is left unset by ingestion; Module 3 owns decline classification
- **Milestone:** M7b
- **Decision:** What does Module 2 ingestion write for `is_hard_decline`, and who
  classifies a decline as hard vs soft?
- **Chosen:** Ingestion does **not** classify a decline. Concretely:
  - the `PaymentDegradationContext.is_hard_decline` field is typed
    `bool | None` with default `None`, and ingestion **leaves it unset** (`None`,
    meaning "not yet classified");
  - ingestion preserves the raw Razorpay `error_code` verbatim as
    `context.decline_code`;
  - ingestion does **not** read, interpret, or branch on Razorpay `error_reason`
    (or `error_source` / `error_step`) — no heuristic, no lookup table, no
    classifier of any kind runs in Module 2;
  - `is_hard_decline` stays `None` until a later owning module sets it. That
    owning module is the **Diagnosis Engine (Module 3)** (Blueprint Part C item 4
    / §3.1), which owns all diagnostic / root-cause classification.
- **Alternatives:** Keep `is_hard_decline: bool` default `False` (a hard/soft
  verdict ingestion has no basis to make); build an `error_reason`-based
  heuristic in Module 2 now (a second classifier Module 3 would immediately
  replace).
- **Reasoning:** `None` is the honest "unknown". The field was `bool` with a
  `False` default from M1; admitting `None` is the minimal change that lets
  ingestion record "unknown" without asserting a classification. It also keeps a
  single owner (Module 3) for the hard/soft decision.
- **Consequence:** `test_context_validation` unaffected (it never asserted the
  old default). Module 3 must set `is_hard_decline` explicitly and must not
  assume `False` for an ingestion-created case. No hard-decline heuristic exists
  anywhere in the codebase.
- **Status:** IN FORCE

## D-059 — Merge carries the abandonment context via a new context field
- **Milestone:** M7b
- **Decision:** How is "the abandonment's context is appended into the surviving
  case's diagnostic input, no signal thrown away" (§2.4) represented?
- **Chosen:** A new optional `PaymentDegradationContext.merged_abandonment_context`
  (`dict | None`). On a Merge, `create_or_attach_case` copies the superseded
  `CHECKOUT_ABANDONMENT` case's (already-validated) `context` dict into it. The
  superseded case is preserved intact with `superseded_by_case_id` set; its
  `status` is **left unchanged** (no `→ CANCELLED` edge is invented — U-01 #1).
- **Alternatives:** Rely only on the `superseded_by_case_id` backlink (Module 3
  would have to follow it); a plain `dict` merge into `context` (blocked by
  `extra="forbid"`); a new `CaseEventType` for the merge (schema-coupled, out of
  M7b scope).
- **Reasoning:** `context` is `extra="forbid"`, so the blueprint's "appended
  into the surviving case's diagnostic input" needs a declared field. The value
  is typed-at-origin (validated when the abandonment case was written), so
  INV-04's intent holds.
- **Consequence:** Consumers of canonical cases must filter
  `superseded_by_case_id IS NULL`.
- **Status:** IN FORCE

## D-060 — Only the live Merge direction is built in M7b
- **Milestone:** M7b
- **Decision:** Build both §2.4 Merge directions?
- **Chosen:** No. Only `payment.failed` arriving after an open
  `CHECKOUT_ABANDONMENT` case. The reverse (`checkout.abandoned` arriving after
  a payment-degradation case) is deferred to the Leg-2 ingestion milestone —
  there is no `checkout.abandoned` producer until then. `dedup.find_supersedable_case`
  only ever looks for `CHECKOUT_ABANDONMENT`.
- **Reasoning:** Leg-2 ingestion does not exist; the reverse direction has
  nothing to trigger it. Building it now would be untestable dead code.
- **Consequence:** Recorded in `DEFERRED.md` under the Leg-2 milestone.
- **Status:** IN FORCE

## D-061 — `CardRetryBudget` seeded at ingestion; the instrument key is the Razorpay token ref
- **Milestone:** M7b
- **Decision:** Ingestion-time retry-budget seeding for Leg 1, and what value
  identifies the card.
- **Chosen:** For a card `payment.failed`, upsert one `CardRetryBudget` at
  `attempts_used_24h = attempts_used_30d = 1`, in the **same database
  transaction** as the case (§2.7 / Part A §3). Idempotent: **seed if absent,
  no-op if present** — per-decline increments are Module 5's `RETRY_PAYMENT`
  concern. No row is written when the payload carries no card instrument
  reference. **No `UPIRetryBudget` seeding** on the Leg-1 path — UPI AutoPay is
  a mandate-scoped Leg-3 concern.

  On the card key:
  - the value stored is `COALESCE(token_id, card_id)` — the **Razorpay
    tokenised card reference** that the webhook payload actually provides;
  - **Torque never receives or stores a PAN** — Razorpay only ever sends the
    tokenised reference;
  - it is written into the existing `CardRetryBudget.card_token_hash` column.
    **That column name is inherited from the blueprint / Module-1 schema and is
    NOT renamed in M7b** — renaming it would be needless schema churn;
  - **M7b performs no PAN hashing** and adds no hashing code;
  - a keyed-HMAC / pepper representation of the instrument key is a **future
    security-hardening item — explicitly NOT part of M7b** and not started.
  - **No new column** is added.
- **Alternatives:** Defer all seeding to M7c (breaks the blueprint's "same
  transaction as the case" requirement); rename `card_token_hash` now (schema
  churn for no functional gain); implement keyed-HMAC hashing now (a security
  subsystem out of the approved M7b scope).
- **Reasoning:** The blueprint binds seeding to case creation. The stored value
  is already a non-PAN token; the column name predates this milestone; keeping
  both unchanged is the minimal correct step and leaves hardening as a clean,
  separately-scoped follow-up.
- **Consequence:** `DEFERRED.md` tracks: keyed-HMAC/pepper instrument-key
  hardening; `UPIRetryBudget` seeding; per-decline increment semantics.
- **Status:** IN FORCE

## D-062 — Ingestion identity resolution: phone, then email, then create
- **Milestone:** M7b
- **Decision:** How does an ingestion-created case get its `counterparty_id`?
- **Chosen:** Match an existing global `Counterparty` by exact `phone`, then
  exact `email`; create one if neither matches. New counterparties default
  `payment_failure_nudge_consent=False`, `whatsapp_opt_in=False`,
  `language_pref` default. `Merchant_Counterparty` is found-or-created via
  `TenantScope`. `Counterparty` matched/created through the raw session (global,
  D-002).
- **Alternatives:** A dedicated match key (Razorpay `customer_id`); a fuzzy
  matcher.
- **Reasoning:** The blueprint has no identity spec; exact phone/email is the
  simplest safe default. Safe consent defaults because ingestion has obtained no
  consent.
- **Consequence:** **Known limitation:** if a person changes phone *and* email
  between signals, a duplicate identity row is created. Stated limitation, not a
  compliance failure — erasure/consent operate correctly per row.
- **Status:** IN FORCE

## D-063 — `Event.processed = True` == "this Event finished its ingestion journey"
- **Milestone:** M7b (supersedes D-056)
- **Decision:** Semantics of `Event.processed`.
- **Chosen:** `True` once the Event has terminated in one M7b outcome:
  self-recovered (interim capture), case created, or a case already existed for
  it. A still-buffering `payment.failed` stays `False`. M7b **never**
  retroactively flips an unrelated/earlier Event's flag — a later case Merge
  supersedes a *case*, not the abandonment's originating Event.
- **Alternatives:** "all related business activity resolved" (too broad — that's
  Module 7); leave it `False` (M7a's interim state).
- **Reasoning:** The flag tracks the ingestion pipeline's own progress on one
  signal, nothing wider.
- **Status:** IN FORCE

## D-064 — Celery beat (static, in-code) for the §2.5 60-second job
- **Milestone:** M7c
- **Decision:** What runs the systemic-detection job every 60 s?
- **Chosen:** A Celery **beat** schedule entry
  (`celery_app.conf.beat_schedule["systemic-detection"] = {task:
  "torque.ingestion.detect_systemic", schedule: 60.0}`). The task
  (`tasks.detect_systemic_task`) opens **one** `session_scope()` transaction and
  calls `systemic.run_systemic_detection`. Dev command:
  `celery -A torque.ingestion.celery_app:celery_app beat`.
- **Alternatives:** Temporal (multi-day workflow engine — wrong shape); a
  Postgres `scheduled_jobs` table + poller; a bespoke scheduler thread.
- **Reasoning:** The job is short (two `COUNT` queries + a bounded per-merchant
  sweep, sub-second) — not a long-running workflow. Celery beat is the
  Python-native periodic-task mechanism and reuses the M7b broker-only
  Celery/Redis setup. **No** Temporal dependency, **no** `PlaybookRun`, **no**
  advisory locks, **no** per-merchant fan-out, **no** `docker-compose` worker
  service (dev command + eager-mode tests only).
- **Consequence:** Running the scheduler is a dev/ops step; if beat is down,
  detection simply does not run (fails safe — no false holds).
- **Status:** IN FORCE

## D-065 — M7c ships `NETWORK_WIDE` only; `ISSUER_SPECIFIC` is deferred (blocked)
- **Milestone:** M7c
- **Decision:** Which systemic-detection tier does M7c implement?
- **Chosen:** `NETWORK_WIDE` only — aggregate `payment.failed` rate per merchant.
  `ISSUER_SPECIFIC` is **not implemented** and cannot be, faithfully: no issuer /
  BIN / acquirer / route value is extracted from any payload or stored on
  `Event`, on any leg context, or on `RevenueLeakCase` (`Network` is
  `MASTERCARD|VISA` only). M7c does **not** read arbitrary Razorpay JSON at
  detection time to manufacture issuer aggregation, and does **not** add issuer
  columns or touch the M7b context/schema.
- **Alternatives:** parse `payload.payment.entity.card.issuer` from `Event.raw_payload`
  at detection time (fragile, method-dependent, absent for many payments);
  extend M7b ingestion to persist an issuer (schema/context change, scope creep).
- **Reasoning:** Walking skeleton — prove `NETWORK_WIDE` end to end first. Issuer
  extraction is a real, separate design question with its own model impact.
- **Consequence:** `SystemicEvent.scope=NETWORK_WIDE`, `issuer_code=None`,
  `network=None` always in M7c. Tracked as **U-08** (issuer/BIN/acquirer
  extraction — field, source, owning model, owner TBD).
- **Status:** IN FORCE

## D-066 — M7c adds `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` as an approved dormant edge (U-01 #3)
- **Milestone:** M7c
- **Decision:** Resolve U-01 #3 — the §2.5-vs-§4 collision where the sweep prose
  implies active cases can be held but the §4 diagram permits only
  `DETECTED → SYSTEMIC_HOLD`.
- **Chosen:** Add exactly `CaseStatus.SYSTEMIC_HOLD` to
  `_TRANSITIONS[CaseStatus.PLAYBOOK_ACTIVE]` in `src/torque/state_machine.py`,
  and drop that edge from the module docstring's "NOT YET ADDED" list. The edge
  is **legal but dormant**: `transition_case` executes it with the existing
  guard architecture (no `guards.py` change — `RevenueLeakCase.status` has no
  `before_flush` guard; `transition_case`/`assert_transition` is the enforcement
  point), the trigger string is `"systemic_network_wide"`, and a
  `STATUS_CHANGED` `CaseEvent` is emitted automatically. **M7c produces no
  `PLAYBOOK_ACTIVE` case and no code path drives the edge** — its systemic job
  sweeps `DETECTED` only. Resume stays the existing `SYSTEMIC_HOLD → DIAGNOSING`
  (§3 "re-queued for diagnosis in a batch"); there is deliberately **no**
  `SYSTEMIC_HOLD → PLAYBOOK_ACTIVE` restoration edge.
- **Alternatives:** defer the edge to Module 5 (contradicts CURRENT_STATE which
  assigned it to M7c); also add `DIAGNOSING → SYSTEMIC_HOLD` (not in §4, not in
  U-01 — not added).
- **Reasoning:** Makes §2.5's "sweep active cases" representable without building
  Module-5 playbook execution or run-recovery semantics. No existing transition
  becomes ambiguous (`_TRANSITIONS` maps state→targets; only `PLAYBOOK_ACTIVE`'s
  set changes; `SYSTEMIC_HOLD`'s outgoing set stays `{DIAGNOSING}`;
  `TERMINAL_STATUSES` / `is_terminal` / the `PARTIALLY_RECOVERED`-B2B special
  case are untouched).
- **Consequence:** Module 5 owns driving the edge and defining what "resume a
  mid-run case" means. `git diff HEAD -- src/torque/state_machine.py` for M7c
  contains **only** this edge + the docstring cleanup.
- **Status:** IN FORCE — resolves `UNRESOLVED.md` U-01 #3.

## D-067 — Stateless aggregate resolution; no `below_threshold_since`, no schema
- **Milestone:** M7c
- **Decision:** How is "failure rate has stayed below threshold for the sustain
  window" (§3) computed?
- **Chosen:** On each run, recompute failures/min over the trailing
  `systemic_sustain_window_minutes`; if it is `< multiplier × baseline_rate`,
  pass `minutes_below_threshold = sustain_window_minutes` to the existing
  `compliance.systemic.systemic_resolved` predicate (else `0`). No
  `SystemicEvent.below_threshold_since` column, no per-minute persistence state,
  no circuit-breaker table, no migration.
- **Alternatives:** a `below_threshold_since` timestamp column (migration);
  true per-minute consecutive checks over the window (more queries).
- **Reasoning:** At demo scale the aggregate is sufficient and idempotent. A
  brief sub-window spike delays resolution (conservative); the window must be
  wholly below threshold to resolve, so a brief dip cannot resolve prematurely.
- **Consequence:** Noted as an approximation of "Y consecutive minutes"; a
  refinement is possible later without schema change.
- **Status:** IN FORCE

## D-068 — No new `CaseEventType` for systemic hold/resume
- **Milestone:** M7c
- **Decision:** Does M7c add a `SYSTEMIC_HOLD_RESOLVED` (or similar) event type?
- **Chosen:** No. Hold = `STATUS_CHANGED` (from `transition_case`) **plus**
  `SYSTEMIC_HOLD_APPLIED` (blueprint §2.5 asks for it explicitly, carrying
  `systemic_event_id` / `scope` / `issuer_code=None`). Resume =
  `STATUS_CHANGED{trigger: "systemic_resolved"}`. `CaseEventType` stays at 10
  members.
- **Alternatives:** a dedicated resume event type (convenient, not required).
- **Reasoning:** The blueprint does not require a resume-specific event, and
  D-007 makes adding a `CaseEventType` a deliberate schema-coupled act.
- **Status:** IN FORCE

## D-069 — §2.7 counter seeding is rail-specific; `UPIRetryBudget` seeding is a Leg-3 requirement
- **Milestone:** M7c
- **Decision:** M7c's §2.7 retry-budget obligation, and where `UPIRetryBudget`
  seeding lives.
- **Chosen:** §2.7's "seed `CardRetryBudget`/`UPIRetryBudget` … if
  payment-instrument event" is **rail-specific**, not a generic seeder (D-016:
  "three retry rails, three separate entities, none a template"). Each rail's
  originating-decline producer seeds its own entity in the case transaction:
  - card `payment.failed` → `CardRetryBudget` — **done in M7b** (D-061). M7c does
    not touch it.
  - UPI-AutoPay `subscription.charged.failed` (`mandate_type=UPI_AUTOPAY`) →
    `UPIRetryBudget` (`mandate_id`-scoped; "UPI AutoPay has no card token") —
    **assigned to the Leg-3 milestone as a definition-of-done requirement**,
    tied to that producer and `SubscriptionFailureContext`. **M7c implements no
    UPI ingestion, no mandate association, no `UPIRetryBudget` creation, no UPI
    retry schedule (`T+24h/T+72h/T+168h` is NOT in v7), no `NACHRetryPolicy`
    seeding, and no generic seeding abstraction.**
- **Alternatives:** a generic budget-seeding abstraction now (contradicts D-016;
  premature abstraction over three structurally different shapes); defer all
  seeding to a later milestone (breaks the blueprint's "same transaction as the
  case").
- **Reasoning:** A Leg-1 one-off `payment.failed` (even via UPI collect/intent)
  is not a mandate — no `mandate_id`, so `UPIRetryBudget` cannot and must not be
  created on that path. M7c adds no mandate-failure producer, so its §2.7
  obligation is already satisfied by M7b.
- **Consequence:** M7c tests explicitly assert no `UPIRetryBudget` row is ever
  created by systemic processing or the ingestion hook. The existing UPI hard
  cap / execution-window rules (`compliance.retry_rails`) are unchanged and are
  not licence to build a UPI producer.
- **Status:** IN FORCE — the Leg-3 `UPIRetryBudget`/`NACHRetryPolicy` seeding it
  points to was delivered in **Milestone 8** (D-072).

## D-070 — Razorpay `payment.method` → `MandateType` map; unknown → `NACH`
- **Milestone:** M8 (Leg 3)
- **Decision:** How does a `subscription.charged.failed` payload's payment
  `method` become `SubscriptionFailureContext.mandate_type`? The blueprint names
  the `MandateType` enum (`UPI_AUTOPAY | NACH | CARD`) but gives no Razorpay map.
- **Chosen:** `upi → UPI_AUTOPAY`, `card → CARD`,
  `emandate / nach / netbanking → NACH`; **anything else / missing → `NACH`**.
  Implemented as `payloads.mandate_type_from_method` + `_METHOD_TO_MANDATE`.
- **Alternatives:** raise / skip case creation on an unknown method (loses a
  verified signal); default unknown to `CARD` or `UPI_AUTOPAY` (less
  conservative — those rails have network-enforced caps and windows).
- **Reasoning:** The three main mappings are unambiguous. `NACH` is the
  conservative fallback: a bank-account debit posture that is clearing-cycle
  aware with a **self-imposed** (not network-enforced) ceiling — the safest
  place to land an unrecognised recurring instrument.
- **Consequence:** A degenerate/thin verified payload still produces a case
  (`mandate_type = NACH`), consistent with the M7b "sparse case, not a 500"
  philosophy. Routine data-mapping decision; no blueprint conflict.
- **Status:** IN FORCE

## D-071 — Leg-3 self-recovery buffer mirrors Leg-1; interim match on `subscription_id`
- **Milestone:** M8
- **Decision:** Shape of the `subscription.charged.failed` self-recovery buffer.
- **Chosen:** A parallel module `torque.ingestion.subscription` mirroring
  `buffer.py` / `cases.py`: `resolve_subscription_buffered_event` runs after a
  **30 s** delay (`PolicyConfig.subscription_failure_buffer_seconds`, already
  declared), looks for an interim `subscription.charged` `Event` for the **same
  merchant and same `subscription.entity.id`** with `received_at >= failure.received_at`;
  found → `Event.processed = True`, no case, `SELF_RECOVERED`; else →
  `create_subscription_case`. Same `BufferOutcome` enum, same `_session_scope`
  seam, same idempotency guards (`source_event_id` check, `processed` check).
- **Alternatives:** generalise `buffer.py`/`cases.py` to be leg-parameterised
  (touches verified M7b code substantially — rejected per "do not redesign
  verified architecture merely because another implementation would be cleaner");
  match the interim charge on `payment_id` (Razorpay reissues a new `payment_id`
  for the retry, so `subscription_id` is the stable key).
- **Reasoning:** Blueprint §2.3 ("apply the same pattern … with a shorter
  buffer"). A parallel ~150-line module keeps the verified Leg-1 path untouched.
- **Consequence:** `webhooks.py` dispatch gains an `elif event.type ==
  SUBSCRIPTION_FAILED` branch enqueuing `resolve_subscription_buffered_event_task`
  with `countdown = 30`. `subscription.charged` (success) is persisted only, not
  enqueued (like `payment.captured`). No cross-leg dedup for Leg 3 (§2.4 is
  Leg 1 ↔ Leg 2).
- **Status:** IN FORCE

## D-072 — Leg-3 rail-specific retry-budget seeding (§2.7 / Part A §3)
- **Milestone:** M8
- **Decision:** Which retry entity does a `subscription.charged.failed` seed, and
  with what initial state?
- **Chosen:** Rail-specific, keyed off `mandate_type` (D-016: three entities, no
  shared template), in the same transaction as the case:
  - `UPI_AUTOPAY` → `UPIRetryBudget(mandate_id, merchant_id)` with
    `attempts_used = 1` — "includes the original attempt" (Part A §3); `hard_cap`
    stays the NPCI-locked default `3`; `mandate_cancelled_at` NULL.
  - `NACH` → `NACHRetryPolicy(mandate_id, merchant_id)` with
    `clearing_cycle_status = RETURNED` (a failed charge = a returned
    presentment), `dishonour_count_this_fy = 1`, `return_reason_code = NULL`
    (the real NPCI return code comes from the bank return file — Module 5 — not
    this webhook's generic `error_code`, which also exceeds the 16-char column),
    `retry_eligible_after = NULL` (next batch clearing window — Module 5).
  - `CARD` → `CardRetryBudget` via the **reused** `cases.seed_card_retry_budget`
    (Part A §3: `CardRetryBudget` applies to `mandate_type = CARD` too). That
    helper was renamed from `_seed_card_retry_budget` to a public name since it
    is now shared across `cases` and `subscription`.
  - `mandate_id` is **`payment.entity.token_id` only** — Razorpay's canonical
    handle for the authorised mandate (UPI mandate token / bank e-mandate token /
    card-on-file token). A `subscription.id` is **never** substituted: the
    blueprint keeps `mandate_id` and `subscription_id` as distinct
    `SubscriptionFailureContext` fields and `UPIRetryBudget` is "scoped
    per-mandate" (Part A §3). When the payload carries no token, `mandate_id` is
    stored `""` and **no** `UPIRetryBudget` / `NACHRetryPolicy` row is written —
    exactly as a card payment with no instrument reference seeds no
    `CardRetryBudget` (D-069). Corrected in the M8 mandate-identity verification
    pass (the initial cut had a `subscription.id` fallback — removed).
  - Each seeder is **idempotent** — seed-if-absent, no-op if the
    `UNIQUE(mandate_id, merchant_id)` row exists.
- **Alternatives:** a generic seeding abstraction (contradicts D-016); defer all
  Leg-3 seeding (breaks §2.7 "same transaction as case creation").
- **Reasoning:** Blueprint §2.7 + Part A §3. Multi-decline increments,
  `mandate_cancelled_at` on the 4th attempt, and the real NACH return code /
  `retry_eligible_after` are all Module-5 concerns (post-`RETRY_PAYMENT`), not
  ingestion.
- **Consequence:** M8 tests assert exactly one rail entity per case and no
  cross-rail contamination. `_METHOD_TO_MANDATE` (D-070) drives which seeder runs.
- **Status:** IN FORCE

## D-073 — The M7c systemic hook applies to Leg-3 cases; the systemic rollup does not yet count subscription failures
- **Milestone:** M8
- **Decision:** How does Leg 3 interact with M7c systemic detection?
- **Chosen:** `create_subscription_case` calls the existing
  `systemic.apply_active_hold_if_any` — a `SUBSCRIPTION_FAILURE` case created
  during an active `NETWORK_WIDE` `SystemicEvent` is born `SYSTEMIC_HOLD` (§2.7),
  same as Leg 1. **But** the systemic detection *rollup*
  (`systemic._failure_count` / `_baseline_failure_rate`) still counts only
  `Event(type == "payment.failed")` — it does **not** yet include
  `subscription.charged.failed`. Extending the rollup to subscription failures is
  deferred (see `DEFERRED.md`).
- **Alternatives:** extend the rollup now (scope expansion into M7c's detection
  logic; the blueprint §2.5 does not enumerate which event types feed the rate).
- **Reasoning:** The §2.7 hold-on-ingest is a small reuse and is clearly required
  ("check systemic hold — if active, set SYSTEMIC_HOLD" applies to every ingested
  case). Whether an issuer/network outage should be *detected* from subscription
  failures too is a separate, deferrable refinement — consistent with the
  walking-skeleton approach and with M7c leaving `ISSUER_SPECIFIC` deferred.
- **Status:** IN FORCE — the §2.7 hook is likewise applied to Legs 2 & 4 (D-078);
  the rollup still counts `payment.failed` only.

## D-074 — Leg 2 `checkout.abandoned` via a signed internal injection endpoint
- **Milestone:** Module 2 completion run
- **Decision:** How is `checkout.abandoned` ingested — there is no Razorpay
  webhook for it (§2.6 / Part D item 1)?
- **Chosen:** The confirmed demo-scope default: a **signed internal endpoint**
  `POST /internal/checkout-abandoned/{merchant_id}` (`torque.api.checkout_injection`).
  It mirrors the Razorpay webhook (INV-23) exactly — HMAC-SHA256 over the raw
  body (constant-time, `verify_razorpay_signature` reused) against a **dedicated**
  `Settings.checkout_injection_secret`; `X-Torque-Signature` header;
  `X-Torque-Event-Id` header for idempotency (**header-sourced, never
  payload-derived** — §2.5); unknown merchant / bad sig / unset secret / missing
  id → empty HTTP 200, no `Event`; else one `Event(type="checkout.abandoned")`
  via `TenantScope` + enqueue `create_checkout_case_task`. **No self-recovery
  buffer** (§2.3) — immediate task. Torque-defined body shape:
  `{"event": "checkout.abandoned", "payload": {"checkout": {"entity":
  {"cart_id", "cart_value" (paise), "drop_stage", "payment_method_attempted",
  "contact", "email"}}}}`. A real storefront SDK/pixel is a separate build item
  (Part D item 1) and is **not** built.
- **Alternatives:** a real storefront pixel now (Part D item 1 explicitly defers
  it); reuse the Razorpay webhook path (it is a different signature scheme).
- **Reasoning:** §2.6 spells out "a signed internal endpoint … HMAC keyed
  per-merchant, same pattern as §2.2".
- **Consequence:** `Settings.checkout_injection_secret` added. New router in
  `create_app()`.
- **Status:** IN FORCE

## D-075 — §2.4 cross-leg correlation completed bidirectionally
- **Milestone:** Module 2 completion run
- **Decision:** Implement the reverse §2.4 direction (a `checkout.abandoned`
  arriving after an open `PAYMENT_DEGRADATION` case).
- **Chosen:** `dedup.find_supersedable_payment_case` — the abandonment's
  `cart_id` is matched against an open, non-terminal, non-superseded
  `PAYMENT_DEGRADATION` case's **`source_event.raw_payload` `order_id`** (the
  payment leg's typed context has no `cart_id`/`order_id` field), same
  `(merchant_id, counterparty_id)`, within
  `PolicyConfig.cross_leg_dedup_window_hours`. On a hit,
  `checkout.create_checkout_case` creates the `CHECKOUT_ABANDONMENT` case then
  immediately sets its `superseded_by_case_id` to the pre-existing payment case
  (which stays canonical) and merges its context into the survivor's
  `context["merged_abandonment_context"]`. **Symmetric end-state** with the
  forward direction (M7b `cases.create_or_attach_case`): the abandonment is
  always the superseded/narrower case; the payment case is always canonical with
  the merged context; the superseded case's `status` is **unchanged**. Same
  candidate-narrowing strategy (`merchant_id` + `counterparty_id` + `leg_type` +
  `opened_at`, id match in Python) — **no JSONB expression index**.
- **Alternatives:** store `order_id` on `PaymentDegradationContext` at Leg-1
  creation time (touches verified M7b context/code); a JSONB index (rejected —
  demo scale, and the instruction forbids it).
- **Reasoning:** §2.4 last paragraph — "runs symmetrically regardless of which
  event type arrives first".
- **Consequence:** `dedup.py` gains the second finder; `checkout.py` owns the
  reverse-merge write. `cases.create_or_attach_case` (forward) is unchanged.
- **Status:** IN FORCE

## D-076 — Merge audit trail: no new `CaseEventType` (Option A)
- **Milestone:** Module 2 completion run
- **Decision:** How is a supersession audited?
- **Chosen:** The blueprint's existing mechanism only:
  `superseded_case.superseded_by_case_id = surviving_case.id` (the canonicality
  relationship) + the survivor's `merged_abandonment_context` + each case's
  preserved `source_event` and `STATUS_CHANGED` history. "Which case was
  superseded / which is canonical / which leg produced the survivor / why" are
  all reconstructable from these. **No `CASE_SUPERSEDED`, no new `CaseEventType`,
  no new payload schema, no `ALTER TYPE` migration** — the blueprint §4 CaseEvent
  vocabulary stays closed at 10 (D-007), reaffirming D-059 and D-068.
- **Alternatives:** add a `CASE_SUPERSEDED` `CaseEventType` (Option B) — this was
  raised as an "authoritative" requirement in a Module 2 instruction but that
  framing was erroneous: no such type exists in the blueprint §4 table and
  D-007/D-041/D-059/D-068 govern the locked vocabulary; the maintainer confirmed
  Option A.
- **Consequence:** Consumers of "currently actionable" cases must filter
  `superseded_by_case_id IS NULL` (unchanged from M7b).
- **Status:** IN FORCE

## D-077 — Leg 4 `invoice.overdue` → `B2BInvoice` + §3 case grouping
- **Milestone:** Module 2 completion run
- **Decision:** The `invoice.overdue` ingestion path and its grouping.
- **Chosen:** Razorpay-webhook dispatch → **no buffer** (§2.3) → immediate
  `ingest_invoice_task` → in one `session_scope`: resolve counterparty; apply the
  **locked §3 grouping rule** — if an open (non-terminal, non-superseded)
  `B2B_RECEIVABLE` case exists for `(merchant_id, counterparty_id)` the new
  `B2BInvoice` attaches to it (**no new case**, `CASE_ATTACHED`), else a new
  `B2B_RECEIVABLE` case is created with `context = {}` (`CASE_CREATED`) — **no
  time window**. `case.amount_at_risk` is maintained as Σ `outstanding_amount`
  across the thread. Razorpay `payload.invoice.entity` mapping:
  `original_amount = amount` (paise→₹); `outstanding_amount = amount_due`
  (clamped to `[0, original]` to satisfy the CHECKs; falls back to
  `amount − amount_paid`); `due_date` from `expire_by` else `date` (unix→date;
  today if absent); `days_overdue = max(0, today − due_date)`; `gst_inclusive`
  from `gst`/`tax_amount` presence; `payment_terms = terms[:64]`. Idempotency:
  `Event.idempotency_key` UNIQUE + the `event.processed` guard + a
  `source_event_id` check on the CREATE path. **No `razorpay_invoice_id`
  column** — Razorpay fires `invoice.overdue` once per invoice; a redelivered
  event is caught by the existing mechanism. New `BufferOutcome.CASE_ATTACHED`.
- **Alternatives:** a bundling time window (§3 explicitly says "none"); a schema
  column for the Razorpay invoice id (not needed, and the instruction forbids
  speculative schema).
- **Reasoning:** §3 "Grouping logic (locked, no ambiguity left for Module 2)".
- **Status:** IN FORCE

## D-078 — §2.7 systemic hook applied to Legs 2 & 4; rollup unchanged
- **Milestone:** Module 2 completion run
- **Decision:** How do Legs 2 & 4 interact with M7c systemic detection?
- **Chosen:** `checkout.create_checkout_case` and `b2b.ingest_invoice` call
  `systemic.apply_active_hold_if_any` on the **canonical** case they create (not
  on a case being immediately superseded; not on a Leg-4 attach where no case is
  created) — a case born during an active `NETWORK_WIDE` `SystemicEvent` is
  `SYSTEMIC_HOLD` (§2.7), same as Legs 1 & 3. The systemic detection **rollup**
  is unchanged — it counts `Event(type="payment.failed")` only (D-073);
  `checkout.abandoned` and `invoice.overdue` are not failure-rate signals and do
  not feed it.
- **Reasoning:** §2.7 "check systemic hold — if active, set SYSTEMIC_HOLD"
  applies to every ingested case. §2.5 is a payment-rail outage detector.
- **Status:** IN FORCE

## D-079 — `suggested_timing_adjustment` is a new case column; payday hint covers both NSF codes
- **Milestone:** Module 3 — Diagnosis Engine
- **Decision:** Where does the §3.4 `suggested_timing_adjustment` diagnosis output
  persist, and which root causes emit it?
- **Chosen:** A new nullable `revenue_leak_case.suggested_timing_adjustment`
  `VARCHAR(64)` column (migration **0014**, additive). The Diagnosis Engine writes
  the symbolic label `"next_month_end_working_day"` for the NSF soft-decline root
  causes of **both** legs (`NSF_SOFT_DECLINE` for subscription — the code §3.4
  names — **and** `ISSUER_SOFT_DECLINE_NSF` for payment: the same "insufficient
  funds → retry after payday" situation), `None` otherwise. It is a symbolic
  label, not a computed date — the concrete fire time is Module 4 §4.3 / Module 5.
- **Alternatives:** put it in the `DIAGNOSIS_COMPLETED` payload (that schema is
  closed at three keys, D-007 discipline); put it in the typed leg contexts (they
  `extra="forbid"`, and `B2B_RECEIVABLE` has none); have Module 4 recompute it
  (§4.3 says Module 4 *reads* it *from the diagnosis*, so it must be persisted).
- **Reasoning:** §3.4 says the value is *stored* as a signal *separate from*
  `diagnosis_confidence`; the parallel with the existing `root_cause_code` /
  `diagnosis_confidence` case columns (also diagnosis outputs) makes a case column
  the obvious minimum home. This is a Part-C-style addition to Module 1's schema.
- **Consequence:** one additive column; `git diff` of `state_machine.py` /
  `guards.py` stays empty; schema-introspection subset checks (`<=`) unaffected.
- **Status:** IN FORCE

## D-080 — Module 3 is not auto-dispatched from Module 2 ingestion (orchestration deferral)
- **Milestone:** Module 3 — Diagnosis Engine
- **Decision:** Does §2.7's "dispatch to Module 3 (Diagnosis)" get wired into the
  Module 2 ingestion legs in this run?
- **Chosen:** **No.** The Diagnosis Engine is delivered as an independently
  invocable surface — `diagnose_case(session, case_id)` + the `diagnose_case_task`
  Celery task — but no ingestion leg enqueues it. The cross-module *trigger* is an
  orchestration-layer concern left for later.
- **Alternatives:** enqueue `diagnose_case_task` from each leg's case-creation path
  (Legs 1–4) and from the §2.5 systemic-resume batch.
- **Reasoning:** In eager test mode an inline enqueue runs diagnosis synchronously
  *inside* ingestion, which would flip a freshly-created case out of `DETECTED`
  and break Module 2's tested post-ingestion contract (30+ tests assert
  `status == DETECTED`). The project's own §2.5 resume path already establishes
  the pattern "move a case to a queued state, let a separate worker complete it"
  (it transitions to `DIAGNOSING` without running diagnosis inline). Wiring the
  trigger is not required for the engine to be complete and correct.
- **Consequence:** Module 2 stays byte-stable except the additive celery
  registration; the engine handles both entry states (`DETECTED` fresh cases and
  §2.5-resumed `DIAGNOSING` cases). The auto-dispatch trigger is tracked in
  `DEFERRED.md` under the orchestration layer.
- **Status:** IN FORCE

## D-081 — Subscription decline code is read from the source Event, not the typed context
- **Milestone:** Module 3 — Diagnosis Engine
- **Decision:** Where does the Diagnosis Engine read the `decline_code` for a
  `SUBSCRIPTION_FAILURE` case, given `SubscriptionFailureContext` has no such field?
- **Chosen:** From the case's **source `Event`** — `payment.entity.error_code` in
  `Event.raw_payload`, read through the tenant scope. `PaymentDegradationContext`
  *does* carry `decline_code` (ingestion copies it there), so the payment leg reads
  it from the context; the subscription context deliberately stores only mandate
  identity (`mandate_id, mandate_type, billing_cycle, subscription_id`).
- **Alternatives:** add a `decline_code` field to `SubscriptionFailureContext`
  (widens a locked typed context for a value already present on the Event);
  copy it into the context at ingestion (a Module 2 change outside this scope).
- **Reasoning:** the raw signal is already persisted verbatim on the Event; reading
  it there needs no schema change and no Module 2 edit, and the tenant-scoped read
  keeps isolation intact.
- **Status:** IN FORCE

## D-082 — §3.2.4 mandate-type facts take highest precedence in subscription diagnosis
- **Milestone:** Module 3 — Diagnosis Engine
- **Decision:** In what order are the subscription rules applied — the §3.2.4
  mandate facts (NACH `PENDING_CLEARING` → `NACH_CLEARING_PENDING`; UPI AutoPay
  `mandate_cancelled_at` set → `UPI_AUTOPAY_CAP_EXHAUSTED`, both confidence 1.0)
  vs. the §3.2.1 network-directive precedence and §3.2.2 decline-code lookup?
- **Chosen:** The mandate facts are checked **first** (highest precedence), then
  the network directive, then the decline code, then the missing-code fallback.
- **Alternatives:** apply them last, following the literal §3.2 step numbering (1
  network directive, 2 decline code, 3 missing, 4 mandate facts).
- **Reasoning:** §3.2.4 calls these "a fact, not an inference" at confidence 1.0
  (a still-clearing NACH batch hasn't actually failed; a cancelled UPI mandate is
  terminal). They are rail-specific and cannot collide with a card MAC tier (a
  UPI/NACH mandate carries no Mastercard/Visa directive), so ordering them first
  changes no real outcome — it only guarantees the definitive fact wins. The
  clearing status / cancellation are looked up (tenant-scoped) from
  `NACHRetryPolicy` / `UPIRetryBudget`; note a `subscription.charged.failed` seeds
  NACH as `RETURNED` (D-072), so the pending-fact branch fires only when a policy
  row is independently in `PENDING_CLEARING`.
- **Status:** IN FORCE

## D-083 — Module 3 consumes `network_directive_tier` but does not extract MAC codes
- **Milestone:** Module 3 — Diagnosis Engine
- **Decision:** Does the Diagnosis Engine perform the §5.3 "first-touch" MAC-code →
  tier lookup from raw payloads when a case has no `network_directive_tier` yet?
- **Chosen:** **No.** Module 3 *consumes* `network_directive_tier` when it is
  already populated on the case (giving TIER_1/TIER_3 precedence per §3.2.1) but
  does **not** extract a raw MAC code from the Event payload and does not call the
  `MacCodeRegistry`. Cases without a tier take the decline-code path.
- **Alternatives:** implement §5.3's "Module 3 at diagnosis time, whichever sees
  the code first" MAC lookup here.
- **Reasoning:** no MAC code is surfaced anywhere for Module 3 to look up —
  ingestion stores the coarse Razorpay `error_code` as `decline_code`, not a
  network decline-advice code, and issuer/BIN/acquirer/route extraction is the
  deferred U-08. Building MAC extraction now would invent the very
  issuer/network-extraction the project has explicitly deferred. `network_directive`
  precedence is still honoured wherever a tier *is* present (e.g. set by a future
  Module 2 enhancement or a test via `apply_network_directive`).
- **Consequence:** the §5.3 first-touch MAC lookup at diagnosis time is tracked in
  `DEFERRED.md`; it is unblocked only when U-08 is resolved.
- **Status:** IN FORCE

## D-084 — `is_hard_decline` derived from root cause; B2B buckets are demo-scope thresholds
- **Milestone:** Module 3 — Diagnosis Engine
- **Decision:** How is `is_hard_decline` (D-058, Module-3-owned) computed, and how
  are the B2B risk buckets drawn from `days_overdue × promise_keeping_rate`?
- **Chosen:** `is_hard_decline` is **derived from the PAYMENT_DEGRADATION
  `root_cause_code`**: `True` for card-expired / fraud-suspected /
  instrument-not-recurring; `False` for the NSF / other-soft / gateway-timeout
  codes; `None` (no verdict) for `UNKNOWN_LOW_CONFIDENCE`. It is written only for
  PAYMENT_DEGRADATION cases (the only leg whose context carries the field), only
  when the verdict is not `None`. B2B bucketing: an **established** counterparty
  (≥3 invoices on record for the merchant **and** a `promise_keeping_rate`) →
  confidence 0.8, bucketed by `days_overdue × (1 − promise_keeping_rate)` with a
  `≥90`-day `DISPUTE_SUSPECTED` coarse fallback; **cold-start** → confidence 0.4,
  bucketed on `days_overdue` alone (`UNKNOWN_RECEIVABLE_RISK` if none). The known
  decline-code seed table (`decline_codes.py`) is likewise demo-scope.
- **Alternatives:** store an independent hard/soft classifier separate from the
  root cause (two sources of truth for the same fact).
- **Reasoning:** the root cause already encodes the hard/soft nature; deriving
  keeps a single source of truth. §3.2 explicitly frames B2B bucketing and the
  decline-code table as rule-based demo-scope lookups Module 3 "owns future
  refinement" of; the specific thresholds/strings mirror the `MacCodeRegistry`
  seed's "architecture locked, mapping is a pre-production checklist" posture
  (Decision M / Part E item 1).
- **Status:** IN FORCE

---

## Notes not recorded as decisions

- The **Git-history incident of 2026-09-02** (a bad commit briefly on `main`,
  then restored by the maintainer) is an operational event, not a design
  decision. It left no trace in the restored tree. Do not treat it as precedent
  for anything.
- Exact **pytest-collected test counts at the completion of M1–M5** could not be
  re-verified in this session (see `MILESTONES.md`); they are recorded there with
  an explicit "unverified" flag.
