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

## D-085 — The playbook catalog is seeded through the ORM, not an Alembic data migration
- **Milestone:** Module 4 — Policy & Playbook Engine
- **Decision:** How are the eleven §4.1 catalog playbooks persisted?
- **Chosen:** An application-level `torque.policy.catalog.seed_catalog(session)`
  that inserts each `PlaybookIdentity` + version-1 `Playbook` **through the ORM**,
  so the `before_flush` guard validates every `steps_graph` / `stopping_rules`
  (incl. the UPI ≤3 ceiling) exactly as it would a hand-authored playbook.
  Idempotent (re-seed inserts nothing; never forks a version 2). The catalog data
  (slugs, leg/mandate discriminators, graphs, rules) lives in `catalog.py` as the
  single source of truth.
- **Alternatives:** an Alembic data migration with raw-SQL INSERTs of the JSON.
- **Reasoning:** a raw-SQL migration bypasses the ORM guard — a malformed catalog
  graph could ship unvalidated, contradicting §4.2's "catch a bad playbook before
  it can ever run". Seeding is not schema; no migration was created for Module 4.
- **Consequence:** deploy/demo/test calls `seed_catalog`. `MacCodeRegistry`
  (migration-seeded, 0006) stays as-is — it has no graph to validate.
- **Status:** IN FORCE

## D-086 — A PLAYBOOK_ACTIVE case with no eligible playbook escalates to human
- **Milestone:** Module 4 — Policy & Playbook Engine
- **Decision:** What does Module 4 do with a `PLAYBOOK_ACTIVE` case whose
  `root_cause_code` has no catalog playbook (§4.1's "non-trivial" wording leaves
  the fraud hard-stop, UPI cap-exhausted, NACH clearing-pending, dispute, and
  subscription card-expired causes deliberately unmapped), or whose merchant has
  **disabled** the matching playbook?
- **Chosen:** Route it `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN` via the **existing
  legal** state-machine edge, writing the normal `STATUS_CHANGED` event (distinct
  `ActivationOutcome.ESCALATED_NO_PLAYBOOK` / `ESCALATED_DISABLED` for
  observability). No `PlaybookRun` is created; the case is never left stuck in
  `PLAYBOOK_ACTIVE`.
- **Alternatives:** invent a playbook for every ≥T root cause (contradicts §4.1
  "non-trivial"); leave the case parked (a permanent limbo); a new state/edge
  (the edge already exists — no change to `state_machine.py`).
- **Reasoning:** §4.1 explicitly gives "one playbook per **non-trivial**
  root_cause_code" — some causes have none by design, and a human is the correct
  handler (close the fraud case, contact the dispute, wait on the clearing). The
  `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN` edge is legal (Section 4) and not
  exclusively Module 6's ceiling-escalation. Module 3 routes all ≥T causes to
  `PLAYBOOK_ACTIVE`; this is the faithful, safe disposition of the ones with no
  automation.
- **Consequence:** fraud-suspected, UPI cap-exhausted, NACH clearing-pending,
  dispute-suspected, and subscription card-expired cases escalate. If a future
  refinement adds a playbook (e.g. mandate-renewal for card-expired), the mapping
  in `selection.py` changes and they stop escalating — no state-machine change.
- **Status:** IN FORCE

## D-087 — `payday_cycle_override_enabled` lives in `Merchant.risk_appetite_config`
- **Milestone:** Module 4 — Policy & Playbook Engine
- **Decision:** Where does the §4.3 merchant payday-override flag (default `true`)
  live, and who applies the suggestion?
- **Chosen:** In the existing `Merchant.risk_appetite_config` JSONB under key
  `payday_cycle_override_enabled` (default `True` when absent) — no schema change.
  `torque.policy.payday` owns the **policy gate** (`payday_override_enabled`,
  `effective_timing_adjustment`): it returns the case's
  `suggested_timing_adjustment` iff the flag is on, else `None`. The actual
  fire-time computation is Module 5 (D-025).
- **Alternatives:** a dedicated `Merchant` column; a `MerchantPlaybookConfig`
  field.
- **Reasoning:** `risk_appetite_config` is documented as the "default max attempts
  / escalation ceiling, etc." bag — a per-merchant policy flag is exactly that.
  The blueprint frames the override as a **runtime substitution** at Module 5's
  timing step, so Module 4 stores nothing extra and only gates the signal.
- **Status:** IN FORCE

## D-088 — Module 4 is not auto-dispatched from Module 3 (orchestration deferral)
- **Milestone:** Module 4 — Policy & Playbook Engine
- **Decision:** Does diagnosis completion automatically enqueue activation?
- **Chosen:** **No** — mirrors D-080. `activate_case` + `activate_case_task` are
  the finished, independently-invocable Module 4 surface, but no Module 3 code
  enqueues them. The cross-module trigger is an orchestration-layer concern.
- **Alternatives:** enqueue `activate_case_task` at the end of `diagnose_case`.
- **Reasoning:** an inline eager enqueue would run activation synchronously inside
  diagnosis and change Module 3's tested post-diagnosis contract (cases end
  `PLAYBOOK_ACTIVE`, no run yet). Same reasoning as Module 2 → Module 3 (D-080).
- **Consequence:** tracked in `DEFERRED.md` under the orchestration layer.
- **Status:** IN FORCE

## D-089 — Run creation writes no CaseEvent; one live run per case; effective rules off the pinned base
- **Milestone:** Module 4 — Policy & Playbook Engine
- **Decision:** Three run-instantiation specifics: does creating a `PlaybookRun`
  write a `CaseEvent`? what makes activation idempotent? which base do effective
  stopping rules merge onto?
- **Chosen:**
  * **No CaseEvent for run creation.** The case is already `PLAYBOOK_ACTIVE`
    (Module 3), so there is no status change, and §4's closed `CaseEvent`
    vocabulary has no "run created" / "playbook selected" type — inventing one
    would violate D-007/D-076. (`STEP_TRANSITIONED` is Module 5's, U-02.) A
    no-playbook/disabled **escalation** does change status → a normal
    `STATUS_CHANGED`.
  * **Idempotency = one live run per case, app-enforced.** `activate_case` is a
    no-op if a `RUNNING`/`PAUSED` run already exists for the case; a terminal run
    (`COMPLETED`/`CANCELLED`/…) does not block a fresh activation. No new DB
    constraint — a case legitimately has multiple runs over its lifetime.
  * **Effective rules merge the merchant override onto the run's PINNED version's
    base** (`resolve_effective_stopping_rules`), reflecting the current override
    (`enabled` gates availability at creation, not resolution — D-023). Save-time
    validation still keys off the latest version (D-023); runtime resolution keys
    off the pinned one, so a run's rules stay coherent with its pinned graph.
- **Alternatives:** a synthetic run-created event; a UNIQUE(case_id) partial
  index; merging onto the latest version at runtime (would let a new publish shift
  an in-flight run's rules).
- **Reasoning:** keeps the audit vocabulary closed, the schema untouched, and
  version pinning meaningful for rules as well as graph.
- **Status:** IN FORCE

## D-090 — Durable `PlaybookRun` execution uses the Postgres-polling driver, not Temporal
- **Milestone:** Module 5 — Execution & Orchestration
- **Decision:** Which durable orchestration engine drives multi-day `PlaybookRun`
  execution (the open half of U-07 / blueprint Decision C)?
- **Chosen:** The **Postgres-polling fallback** (§5.6), selected by the maintainer
  when Module 5 was proposed. A `scheduled_job(job_id, merchant_id, run_id UNIQUE,
  case_id, fire_at, leg_type)` table (migration **0015**) + two stratified
  Celery-beat pollers (10 s for `PAYMENT_DEGRADATION`, 60 s for the other three
  legs). Due rows are claimed `FOR UPDATE SKIP LOCKED`; each step executes in one
  transaction that advances `fire_at` (run continues) or deletes the row (terminal).
- **Alternatives:** Temporal (OSS, self-hosted) — the blueprint's §5.1 stated
  preference; rejected for the build window because it needs a self-hosted cluster
  + the `temporalio` SDK, whereas polling reuses the existing Postgres + Celery
  stack and is fully testable in the harness.
- **Reasoning:** the blueprint fully specifies the fallback ("a working fallback is
  already specified either way", Part E item 8); no new infra/dependency; the
  durable state lives entirely in Postgres, never in Celery/Redis task state (§5.5).
- **Consequence:** resolves U-07's remaining half. Celery is the repeatable-timer
  *trigger* only. Migrating to Temporal later is a driver swap behind the same
  `execute_due_job` tick.
- **Status:** IN FORCE

## D-091 — `STEP_TRANSITIONED` payload settled (resolves U-02)
- **Milestone:** Module 5
- **Decision:** Finalise the provisional `CaseEvent.STEP_TRANSITIONED` payload
  (U-02 / Part E item 3), which Module 5 is the first and only writer of.
- **Chosen:** `{ run_id, from_step_id, outcome, to_step_id?, edge_condition? }`.
  `run_id` adds run attribution (a case may host successive runs; `CaseEvent` has no
  `run_id` column — D-005 — so it lives in the payload). `to_step_id` /
  `edge_condition` are nullable: a terminal step has no next step / edge. `outcome`
  is the `ActionOutcome` that drove edge selection. This reconstructs
  `previous → outcome → next` with case+run attribution and the `CaseEvent`
  timestamp.
- **Alternatives:** keep the 4-field provisional shape (no run attribution; a
  required `to_step_id` cannot represent termination); add a `run_id` column to
  `CaseEvent` (contradicts D-005's single-history-mechanism minimalism).
- **Reasoning:** Module 5 owns settling this (Part E item 3); the additions are the
  minimum needed for faithful reconstruction, not speculative fields.
- **Consequence:** U-02 moves to Resolved. No existing writer changed (Module 5 is
  the first). No `CaseEvent` schema change.
- **Status:** IN FORCE

## D-092 — Module 5 runs the retry/systemic/timing guardrails; the GuardrailEngine facade + Outreach Coordinator are Module 6
- **Milestone:** Module 5
- **Decision:** Where does the §5.2 guardrail sequence split between Module 5 and
  Module 6 (maintainer-confirmed line)?
- **Chosen:** **Module 5** runs, immediately before each action: network hard-stop,
  the rail budgets (Card/UPI/NACH), the §5.2.3 pre-debit 24 h gap **with self-heal
  auto-insert**, and the systemic-hold check; it treats quiet-hours and the UPI
  execution window as **defers** (reschedule the timer), not failures.
  **Module 6** later adds the canonical `GuardrailEngine.check()` facade, the
  Outreach Coordinator (quiet-period / merge / defer policy), and the WhatsApp
  consent + approved-template gate. `torque.execution.guardrails` is structured so
  Module 6 extends it rather than replacing it.
- **Alternatives:** pull the Outreach Coordinator + WhatsApp gate into Module 5 now
  (scope creep into Module 6); enforce nothing (unsafe once real channels attach).
- **Reasoning:** the demo executor performs no real contact, so deferring the
  contact-consent gates to Module 6 is safe; the retry-rail + systemic + timing
  checks are squarely Module 5's execution concern.
- **Consequence:** WhatsApp `whatsapp_opt_in`/template gating and the Outreach
  Coordinator remain Module 6 (DEFERRED.md). Systemic hold is a **BLOCK** that
  follows the `on_blocked` edge (§5.2 literal), not an invented state transition.
- **Status:** IN FORCE

## D-093 — Module 4 → Module 5 dispatch, action channels, and terminal mapping
- **Milestone:** Module 5
- **Decision:** Assorted execution-shape choices with a single sensible answer.
- **Chosen:**
  - **Dispatch trigger deferred:** `schedule_run` (arm a run's first timer) is not
    auto-called by Module 4's `activate_case`; the Module 4 → 5 hand-off is left to
    the orchestration layer, consistent with the earlier inter-module dispatch
    deferrals (D-080 / D-088). Engine + poller are ready and invocable.
  - **Executor is an internal stub (§5.4):** `torque.execution.executor.run_action`
    performs no external I/O and returns `SUCCESS` by default — the seam real
    channel adapters attach to later. No provider integrations in demo scope.
  - **Terminal → case status:** reaching an `ESCALATE_HUMAN` terminal node ⇒ case
    `→ ESCALATED_TO_HUMAN`, run `ESCALATED`; any other terminal, or hitting
    `max_attempts` / `max_duration_days`, ⇒ case `→ EXHAUSTED`, run `COMPLETED`.
    Recovery closure (`RECOVERED`/`CANCELLED`) stays Module 7's out-of-band job.
  - **`max_attempts`** counts executed (non-blocked) Actions for the run — a safety
    bound atop the acyclic graph.
- **Reasoning:** each uses an existing legal state-machine edge and the established
  deferral pattern; none invents domain behaviour or touches `state_machine.py`.
- **Status:** IN FORCE

## D-094 — `max_duration` runs from the first executed action; payday adjusts only the entry step
- **Milestone:** Module 5 corrective pass (audit finding F-1).
- **Decision:** How does `stopping_rules.max_duration_days` interact with a
  deliberately-scheduled first-action delay (a long `timing_offset`, or a §4.3
  payday-cycle target that can sit ~a month out), and to which node does the payday
  substitution apply?
- **Chosen:**
  - **`max_duration_days` bounds the run's *active execution span*, measured from
    its FIRST executed action** (`min(Action.executed_at)`), NOT from
    `PlaybookRun.created_at`. Before any action executes, the duration bound is not
    in effect — a run waiting on its scheduled first fire cannot exhaust. `executed_at`
    is stamped with the execution clock, so it reads consistently in tests and prod.
  - **The §4.3 payday substitution applies only to the entry step** (armed by
    `schedule_run`); advancing steps (`runner._next_fire_time`) use their static
    graph offsets from the previous step's completion. §4.3 says payday adjusts "the
    next node" — the first action after diagnosis — not every rung; applying it to
    all steps pushed each to the next month-end (a 3-step run would take ~3 months).
- **Alternatives:** measure `max_duration` from `created_at` (the pre-fix behaviour
  — silently exhausted the flagship NSF-payday retry before it fired, for failures
  in ~the first half of each month); simply enlarge `PLAYBOOK_NSF_RETRY.max_duration_days`
  (masks the semantic error and still mis-bounds); apply payday to every node.
- **Reasoning:** §4.2/§4.3 — `max_duration` bounds *repetition* of the active
  sequence; a scheduled pre-action wait is a timing delay, not duration spent. Keeps
  `max_duration` meaningful for every playbook (the active span is still bounded)
  while letting policy legitimately time the first action to payday.
- **Consequence:** no schema change (uses existing `Action.executed_at`); no change
  to `state_machine.py`/`guards.py`. Regressions in `tests/test_module5_corrections.py`.
- **Status:** IN FORCE

## D-095 — Poll-batch jobs execute in isolated SAVEPOINTs (per-job atomicity)
- **Milestone:** Module 5 corrective pass (audit finding F-2).
- **Decision:** What is the transaction boundary when one poll pass executes several
  claimed jobs?
- **Chosen:** The batch is still claimed once under `FOR UPDATE SKIP LOCKED` (the
  concurrency guarantee — the row locks are held by the caller's transaction for the
  whole pass), but **each `execute_due_job` runs inside its own
  `session.begin_nested()` SAVEPOINT**. On success the savepoint releases (its writes
  join the caller's transaction and commit with it); on failure only that job's
  savepoint rolls back — it returns `StepResult.ERROR`, its `scheduled_job` row stays
  claimed-but-unmodified and is re-tried on a later poll, and committed sibling work
  is untouched. Each job's own tick (Action + `ActionCase` + `CaseEvent`s +
  retry-budget + `active_step_id` + job row) remains all-or-nothing.
- **Alternatives:** one transaction for the whole batch (the pre-fix behaviour — one
  poison job rolled back and stalled unrelated jobs, a liveness defect); a fully
  independent session/transaction per job (more transactions; awkward with the
  existing `execute_due_jobs(session, …)` signature and the savepoint-joined test
  harness).
- **Reasoning:** the polling driver must isolate one run's failure from others; the
  SAVEPOINT strategy is the simplest that preserves both the `SKIP LOCKED`
  concurrency guarantee and per-job atomicity within the existing architecture.
- **Consequence:** `StepResult.ERROR` added; a persistently-failing job no longer
  blocks its stratum (a dead-letter / failure-count policy remains future work). No
  schema change.
- **Status:** IN FORCE

## D-096 — `PlaybookRun.status = COMPLETED` means execution terminated, not recovered
- **Milestone:** Module 5 corrective pass (audit clarification F-3).
- **Decision:** Clarify the semantics of the terminal run status used for an
  exhausted run (`run COMPLETED` + `case EXHAUSTED`, D-093).
- **Chosen:** `PlaybookRun.status = COMPLETED` means the run's execution has
  terminated — it does **not** by itself mean the case recovered. The authoritative
  recovery signal is the **case**: `RECOVERED` / `EXHAUSTED` and Module 7's
  `recovery_type` / `recovered_amount`. `PlaybookRunStatus` has no `EXHAUSTED` member,
  so `COMPLETED` is the neutral "ran to the end" terminal (D-093); the exhausted-vs-
  recovered distinction lives on the case, not the run. No new enum is added merely
  for naming.
- **Reasoning:** avoids conflating "automation finished" with "money came back";
  keeps recovery a single-source-of-truth case concept.
- **Status:** IN FORCE

## D-097 — `GuardrailEngine.check()` returns the four-way `GuardDecision`; queue reasons are plain strings
- **Milestone:** Module 6 — Compliance & Cross-Leg Guardrail Engine
- **Decision:** What does the single Module 6 facade Module 5 consults return, and
  how is the human-queue `reason` vocabulary modelled?
- **Chosen:** **Intentional deviation (approved, Q-A).** Blueprint §6.2 names the
  return `{ allow: bool, block_reason?: BlockReason }`. `GuardrailEngine.check()`
  returns the existing four-way `torque.execution.guardrails.GuardDecision`
  (`GuardKind.ALLOW / BLOCK / DEFER / AUTO_INSERT_PREDEBIT`) instead — Module 5
  already relies on `DEFER` (quiet-hours, NPCI UPI peak window) and
  `AUTO_INSERT_PREDEBIT` (the §5.2.3 pre-debit self-heal), neither of which a
  bare boolean can express. The facade **composes** the existing predicates
  (`torque.execution.guardrails`, `torque.compliance.*`,
  `torque.coordination.outreach_coordinator`) — it never re-implements them —
  and runs the §5.2 sequence first-failure-wins. `HumanQueueEntry.reason` is a
  plain `String(32)`, not a Postgres enum; the `HumanQueueReason` vocabulary
  lives in `torque.coordination.human_queue` (same posture as
  `MerchantWhatsAppTemplate.approval_status`, D-042).
- **Alternatives:** a literal 2-field return (loses defer / self-heal, or forces
  the runner to keep calling the Module-5 functions directly and the "one
  interface" guarantee is void); a `reason` PG enum + `ALTER TYPE` per addition.
- **Reasoning:** the narrower wording predates Module 5's shipped DEFER /
  self-heal semantics; a superset return regresses nothing and keeps the runner's
  handling unchanged. `git diff HEAD` of `state_machine.py` / `guards.py` stays
  empty.
- **Consequence:** the runner's `_guardrails` delegates to the facade; old
  direct-call tests of `check_retry_guardrails` / `check_contact_guardrails` keep
  passing (those functions remain).
- **Status:** IN FORCE

## D-098 — `priority()` is the Module 8 seam; the placeholder is `amount_at_risk` descending
- **Milestone:** Module 6
- **Decision:** The Outreach Coordinator priority ordering and the human-queue
  `priority` both want Module 8's `(probability × amount_at_risk) ÷ cost`
  (Blueprint Part A §5 / §8) — Module 8 is not built. What do they use now?
- **Chosen:** A single function `torque.coordination.outreach_coordinator.priority(
  case) -> Decimal` returning the **approved placeholder** — `amount_at_risk`
  (Q-B). Merge primary-selection and the human queue's ordering and stored
  `priority` all route through it. Module 8 replaces only this function body.
- **Alternatives:** build a minimal probability/cost lookup inside Module 6
  (scope creep, a second owner for a Module 8 concern); pull Module 8 forward.
- **Reasoning:** keeps the seam explicit and one-line; the "resource-aware
  prioritization" differentiator is then demonstrably Module 8's deliverable, not
  silently faked here.
- **Consequence:** `HumanQueueEntry.priority` is `Numeric(14, 2)`, matching
  `RevenueLeakCase.amount_at_risk` — no schema change when Module 8 lands.
- **Status:** IN FORCE

## D-099 — `GuardDecision` gains `defer_until` / `human_queue_reason`; an OUTREACH_COORDINATOR_DEFERRED DEFER writes a blocked Action
- **Milestone:** Module 6
- **Decision:** How does the Part A §5 defer policy — "deferred to
  `quiet_period_end + timing_offset` … a `CaseEvent` of type `ACTION_BLOCKED`
  with `block_reason = OUTREACH_COORDINATOR_DEFERRED` is written" — fit the
  runner's existing DEFER (bump the timer, write nothing) vs BLOCK (write an
  Action, advance the step) split?
- **Chosen:** Two optional fields added to the frozen `GuardDecision`
  (`defer_until: datetime | None`, `human_queue_reason: str | None`) — the
  four-way `GuardKind` is unchanged. New runner rule: a `DEFER` whose
  `block_reason is OUTREACH_COORDINATOR_DEFERRED` **also** writes an
  `ACTION_BLOCKED` row via `write_action_and_event` (so the `ACTION_BLOCKED`
  `CaseEvent` is written, INV-13) **and** does **not** advance the step
  (deferred, never skipped); if `human_queue_reason` is set it also enqueues the
  case in the same transaction. A plain timing DEFER (UPI peak window, quiet
  hours) is unchanged — no Action, timer bump only. `defer_until`, when set, is
  the exact reschedule target (the coordinator computes it via
  `timing.compute_fire_time`, already pushed into `allowed_hours`).
- **Alternatives:** a fifth `GuardKind` (violates Q-A "four-way"); make it a plain
  BLOCK (advances the step — contradicts "never skipped").
- **Reasoning:** additive, backward-compatible, and the OUTREACH_COORDINATOR_DEFERRED
  block_reason already existed on some DEFER decisions and was simply ignored.
- **Consequence:** used by both the cross-leg quiet period and the
  open-conversation suspension.
- **Status:** IN FORCE

## D-100 — Escalation ceiling: unsuccessful-attempt count, checked before the stopping bounds, `escalation_ceiling <= max_attempts`
- **Milestone:** Module 6
- **Decision:** §6.3 semantics — a ceiling on *what*, checked *where* in the tick,
  and its relationship to `max_attempts`.
- **Chosen (Q-D):**
  - **What:** the count of the run's `Action`s whose outcome is
    `BLOCKED_BY_GUARDRAIL`, `FAILED`, or `NO_RESPONSE`
    (`torque.coordination.outreach_coordinator.UNSUCCESSFUL_OUTCOMES`). An
    `OUTREACH_COORDINATOR_DEFERRED` block counts (it is a `BLOCKED_BY_GUARDRAIL`
    row) — a case that can never get an outreach through legitimately escalates
    to a human. A pure timing DEFER writes no Action and does not count.
  - **Where:** one check (`_escalation_ceiling_hit`) at the **top of
    `execute_due_job`, before `_stopping_rule_hit`** — so an
    `ESCALATED_TO_HUMAN` outcome wins over `EXHAUSTED`, and the run never fires
    another doomed action after tripping the ceiling.
  - **Relationship:** `escalation_ceiling <= max_attempts` is enforced at
    playbook-save time (`_check_escalation_ceiling` in
    `torque.playbooks.validation`, on the base rules and any merged merchant
    override) — the ceiling is a sub-bound on unsuccessful attempts and cannot
    exceed the attempt cap.
  - **Effect:** `transition_case(ESCALATED_TO_HUMAN, trigger="escalation_ceiling")`
    via the existing legal edge, `run.status = ESCALATED`, enqueue
    (`HumanQueueReason.ESCALATION_CEILING`), delete the timer, return
    `StepResult.ESCALATED_CEILING`. This short-circuits before any graph-terminal
    `ESCALATE_HUMAN` node runs — exactly one transition, no collision.
- **Alternatives:** count all executed actions (that is `max_attempts`); check
  after the stopping bounds (EXHAUSTED would pre-empt the human route); a model
  `@validator` on `StoppingRules` (broader blast radius than the two validation
  entry points).
- **Consequence:** one Module-4 test (`test_effective_rules_use_pinned_version`)
  updated to keep its v2 playbook coherent. All eleven catalog playbooks already
  satisfy the bound.
- **Status:** IN FORCE

## D-101 — Persistent `human_queue` table; low-confidence feeder is an origin-agnostic sweep; open-conversation is a 4th reason
- **Milestone:** Module 6
- **Decision:** Is the §6.4 human queue a table or a derived view? How is the
  "low-confidence diagnoses" feeder wired without reopening Module 3? Where does
  the open-conversation "flag for human pickup" land?
- **Chosen (Q-E / Q-H / Q-F):**
  - **A real table** `human_queue` (migration **0016**), `TenantScoped`,
    `UNIQUE(case_id)` as the idempotency backstop, `reason` + `priority` +
    `enqueued_at`. `enqueue()` is a no-op if the case is already queued (first
    reason wins).
  - **Feeder 1** = `sweep_escalated_to_human(session, merchant_id)` — enqueues
    every canonical `status == ESCALATED_TO_HUMAN` case not already queued, with
    reason `LOW_CONFIDENCE_DIAGNOSIS`. **Module 3 is not touched** — the sweep is
    origin-agnostic ("this case is waiting for a human"); a case escalated by the
    Module-4 no-playbook path (D-086) or the §6.3 ceiling is already queued (or
    keeps its own reason) and the sweep skips it.
  - **Feeder 3** = `route_broken_promise(session, promise)` — enqueues a `BROKEN`
    `PromiseToPay`'s case with reason `PROMISE_BROKEN`, nothing else (never a
    harsher automated message). `LOG_PROMISE` execution is still deferred, so the
    hook is tested against a directly-built `BROKEN` promise.
  - **Open-conversation** enqueues with a 4th reason `OPEN_WA_CONVERSATION` —
    §6.4's list of three feeders is not exhaustive of every "flag for human
    pickup" path (Q-F requires the enqueue).
- **Alternatives:** a derived query (cannot store `reason`, no FIFO guarantee); a
  Module 3 edit to enqueue on escalation (touches a completed module).
- **Consequence:** `list_for_merchant` offers `order="priority"` (default:
  priority desc, FIFO tie-break) and `order="fifo"`.
- **Status:** IN FORCE

## D-102 — Merge triggers on two jobs due in one claimed batch; the cross-stratum race is an accepted, documented residual
- **Milestone:** Module 6
- **Decision:** When do two cases merge, and how is the concurrency handled
  without a larger architecture?
- **Chosen (Q-C):** `execute_due_jobs` groups the jobs it has **already claimed
  under one `FOR UPDATE SKIP LOCKED`** by `(merchant_id, counterparty_id)`; a
  group of 2+ whose current steps are non-terminal outreach actions folds via
  `merge.execute_merged` before the solo loop. Higher-`priority` case (D-098)
  owns one `Action`; `credit_weight` is proportional to `amount_at_risk` with the
  primary taking the exact remainder so Σ = `Decimal("1.00000")`. Every
  participating run advances on the send outcome (reusing `runner._advance`) so
  none can re-fire. With no `multi_case_template` the primary sends single-case
  and each secondary gets an `ACTION_BLOCKED`/`OUTREACH_COORDINATOR_DEFERRED` row
  with its timer bumped `>= 1h` and its step held.
  **Residual race (documented in `merge.py`):** the two §5.6 pollers (10 s
  `PAYMENT_DEGRADATION` / 60 s others) claim disjoint job sets, and two workers
  of one stratum also claim disjoint sets — a merge pair split across pollers/
  workers is never co-claimed, so no merge happens and the two cases each get
  their own solo outreach. That is the un-merged baseline (two messages for two
  cases), **not** a double-send of one case; `UNIQUE(run_id)` + `SKIP LOCKED`
  still guarantee each step fires at most once. Closing it would need
  cross-stratum coordination the §5.6 fallback deliberately lacks.
- **Alternatives:** a merge-candidate lock table / cross-stratum queue (a larger
  concurrency architecture — out of scope per Q-C).
- **Consequence:** `StepResult.MERGED` added; tested through `execute_due_jobs`
  and with two real DB connections.
- **Status:** IN FORCE

## D-103 — `DETECTED/DIAGNOSING → CANCELLED` added; reconciliation is the only driver
- **Milestone:** Module 7 — Payment Reconciliation & Attribution
- **Decision:** Resolve U-01 #1/#2 — the two pre-playbook `→ CANCELLED` edges §7.1.4
  needs, and confirm they need no `guards.py` change.
- **Chosen:** Add exactly `CaseStatus.CANCELLED` to `_TRANSITIONS[DETECTED]` and
  `_TRANSITIONS[DIAGNOSING]` in `src/torque/state_machine.py`, and replace the
  docstring's "NOT YET ADDED" block with a note that Module 7 added them. The
  exact diff was **reported before the edit** (per the Module 7 execution rule) and
  shown again in the verification report. `guards.py` is **not** touched —
  `RevenueLeakCase.status` has no `before_flush` guard; `transition_case` /
  `assert_transition` is the enforcement point, and `CANCELLED` was already in
  `TERMINAL_STATUSES`. Only `torque.reconciliation` ever drives these edges,
  trigger `"customer_self_paid"`, writing a `STATUS_CHANGED` + a
  `PAYMENT_RECONCILED` `CaseEvent`. Attribution is always `SELF_RECOVERED` (no
  playbook ran).
- **Alternatives:** a `guards.py` flush guard on `status` (a larger change; the
  existing helper-enforced model already works); a new `CaseEventType` for the
  self-pay (violates D-007's closed vocabulary — `STATUS_CHANGED` +
  `PAYMENT_RECONCILED` already say it).
- **Reasoning:** §7.1.4 is explicit; U-01 assigns these to Module 7. The §4
  diagram already carries the same customer-self-paid `→ CANCELLED` transition out
  of `PLAYBOOK_ACTIVE`.
- **Consequence:** `git diff HEAD -- src/torque/state_machine.py` contains exactly
  the two edges + the docstring; `guards.py` diff empty. Three pre-existing
  state-machine tests were inverted (they had asserted the edges were *not* legal).
- **Status:** IN FORCE — resolves `UNRESOLVED.md` U-01 (fully).

## D-104 — Reconciliation is wired into Module 2's webhook dispatch, not deferred
- **Milestone:** Module 7
- **Decision:** Does the `payment.captured` / `subscription.charged` /
  `payment_link.*` → Module 7 trigger get wired now, or left as an
  orchestration-layer deferral like D-080 / D-088 / D-093?
- **Chosen:** **Wired now.** `torque.api.webhooks` dispatches `reconcile_event_task`
  for `RECONCILE_EVENT_TYPES` immediately after the `Event` write — the same
  pattern as the M7b buffer / M7c systemic / Leg-4 invoice dispatch. **No buffer,
  no countdown:** `reconcile_event` is correct whenever it runs (no case yet →
  `NO_MATCH`; a case present → recover / cancel) and is idempotent on
  `Event.processed`.
- **Alternatives:** deferral (D-080 pattern) — but §7.3 explicitly frames Module 7
  as "a consumer of already-verified `Event` rows from Module 2's pipeline", and
  unlike Modules 3/4/5 there is no downstream module whose tested resting state a
  reconcile dispatch could disturb (Module 7 is the last consumer).
- **Consequence:** `conftest.make_api_client` patches
  `reconcile_event_task.apply_async` (spy `client.reconcile_enqueue`);
  `celery_app` autodiscovers `torque.reconciliation`. A same-session self-recovery
  is still handled by the M7b/M8 buffers (no case is created), and reconcile then
  finds nothing → `NO_MATCH`.
- **Status:** IN FORCE

## D-105 — Matchability, the AGENT_ASSISTED window, and the AMBIGUOUS tie-break
- **Milestone:** Module 7
- **Decision:** Fill the three places §7.1 leaves implicit.
- **Chosen:**
  - **Which cases match (§7.1.2):** open = `PLAYBOOK_ACTIVE`, `ESCALATED_TO_HUMAN`,
    and (B2B only) `PARTIALLY_RECOVERED`; non-superseded. Amount: non-B2B requires
    `amount == amount_at_risk` (a debit either went through or it didn't); B2B
    also allows a partial (`0 < amount < amount_at_risk`). `PAUSED` and
    `SYSTEMIC_HOLD` cases are **not** matched (nothing produces `PAUSED` yet;
    `SYSTEMIC_HOLD` outreach is suppressed by design). The §7.1.4 self-paid
    path targets `DETECTED` / `DIAGNOSING` with `amount == amount_at_risk`.
  - **AGENT_ASSISTED vs SELF_RECOVERED (§7.1.2):** `AGENT_ASSISTED` iff a
    non-blocked `Action` exists for the case (via any `ActionCase` row) with
    `executed_at` within `PolicyConfig.attribution_window_hours` (24h) of the
    reconciliation. A direct `PaymentLink` match (§7.1.1) is always
    `AGENT_ASSISTED`; a §7.1.4 pre-diagnosis close is always `SELF_RECOVERED`.
  - **Multiple non-merged matches → AMBIGUOUS:** attribute the payment to the
    case with the latest executed `Action` (tie-break latest `opened_at`), mark
    it `RECOVERED` with `recovery_type = AMBIGUOUS`, and leave the others open.
    A merged-outreach set (cases sharing one `Action`, §7.1.3) is instead
    recovered together as `AGENT_ASSISTED` with the `ActionCase.credit_weight`
    re-split ∝ `amount_at_risk`.
- **Reasoning:** each is the conservative reading that closes cases correctly
  without over-attributing; `AMBIGUOUS` is a Blueprint §4 `RecoveryType` value
  §7.1 does not otherwise place.
- **Status:** IN FORCE

## D-106 — B2B partial waterfalls oldest-first; a final settlement two-hops to RECOVERED
- **Milestone:** Module 7
- **Decision:** How a partial B2B payment lands, and how a `PARTIALLY_RECOVERED`
  B2B case ever reaches `RECOVERED` (the state machine has no
  `PARTIALLY_RECOVERED → RECOVERED` edge — only R4's `→ PLAYBOOK_ACTIVE`).
- **Chosen:** A partial payment is applied to the case's `B2BInvoice` rows
  **oldest `due_date` first**, decrementing `outstanding_amount`;
  `case.amount_at_risk` is set to the new `Σ outstanding` (INV-33) and
  `case.recovered_amount` accumulates. If outstanding remains → the case
  transitions to (or stays) `PARTIALLY_RECOVERED` and stays open. If a payment
  clears the last balance and the case is already `PARTIALLY_RECOVERED`, Module 7
  performs the **two-hop `PARTIALLY_RECOVERED → PLAYBOOK_ACTIVE → RECOVERED`**
  (both edges legal for B2B), trigger `"reconciliation_final_settlement"` then
  `"payment_reconciled"`, in one transaction. `recovered_amount` on a fully
  recovered case equals the full original balance.
- **Alternatives:** add a `PARTIALLY_RECOVERED → RECOVERED` state-machine edge
  (not in the §4 diagram, not sanctioned by R4 — rejected); match a specific
  invoice by amount (the oldest-first waterfall is simpler and standard AR
  practice).
- **Status:** IN FORCE

## D-107 — Module 7 removes a closed case's human-queue entry
- **Milestone:** Module 7
- **Decision:** When reconciliation closes a case that is in the Module 6 human
  queue, what happens to the queue entry?
- **Chosen:** Module 7 calls `human_queue.remove_for_case(session, case)` on a
  `RECOVERED` / `CANCELLED` close (not on a B2B `PARTIALLY_RECOVERED` — the case
  stays open). A resolved case does not need a human. This is queue-consistency,
  not Agent Console behaviour (Module 10 — Q-I): Module 7 never writes
  `escalation_resolution` or `HUMAN_RESOLVED`.
- **Alternatives:** leave the stale entry (a human would open a closed case);
  a Module 10 sweep (later, and would leave the queue transiently wrong).
- **Status:** IN FORCE

## D-108 — Module 7 is a new `torque.reconciliation` package; zero migrations
- **Milestone:** Module 7
- **Decision:** Package placement and schema footprint.
- **Chosen:** A new top-level package `torque.reconciliation` (`reconcile.py`
  engine, `payloads.py` `payment_link.*` extractors, `tasks.py` Celery task),
  parallel to `torque.ingestion` / `diagnosis` / `policy` / `execution` /
  `coordination`. **No migration:** `recovery_type` / `recovered_amount` /
  `closed_at` (M1), `PaymentLink` (M6a), `B2BInvoice` (M1) and the
  `PAYMENT_RECONCILED` `CaseEventType` (M1) already exist. `find_counterparty`
  (a no-create match) added to `torque.ingestion.identity`;
  `human_queue.remove_for_case` added to `torque.coordination`.
- **Reasoning:** consistent layout; the blueprint's Module 7 needs no new
  entity. A composite `(merchant_id, counterparty_id)` index on
  `revenue_leak_case` was considered and **not** added (demo scale; D-053's
  precedent only adds an index the blueprint names).
- **Status:** IN FORCE

---

## D-109 — Module 8 is a new `torque.scoring` package; the score is PERSISTED on `revenue_leak_case` (migration 0017)
- **Milestone:** Module 8 — Recovery Scoring Model
- **Decision:** Package placement, and whether the recovery score is a
  compute-only function or a stored column.
- **Chosen:** A new top-level package `torque.scoring` (`benchmarks.py` — the
  Decision F cold-start lookup + §8.2 warm-start multiplier; `cost.py` — the
  forward `ChannelRateCard` cost; `score.py` — `RecoveryScore` +
  `compute_recovery_score` + `score_case` / `recompute_open_cases`; `tasks.py` —
  the Celery recompute tasks), parallel to `torque.reconciliation` etc. The
  score **is persisted**: migration **0017** adds three nullable columns to
  `revenue_leak_case` — `recovery_score NUMERIC(18,4)` (for `ORDER BY … DESC`),
  `recovery_score_breakdown JSONB` (the full §8.7 explainable structure), and
  `recovery_score_updated_at TIMESTAMPTZ`.
- **Alternatives:** compute-only (rejected — §8.5's "recompute on creation /
  diagnosis / daily" cadence has nothing to recompute *onto*; the dashboard's
  "top at-risk cases" and Module 9 would each re-derive the formula for every
  open case on every read); a separate `recovery_score` table (rejected —
  one score per case, no history kept in Module 8, a 1:1 side table is pure
  overhead).
- **Reasoning:** the three columns are a **derived cache**: no `guards.py`
  change (it guards only `recovery_type` / `recovered_amount` /
  `network_directive_tier` / `context`), no `CaseEvent`, no status change, no
  new `CaseEventType` (the closed §4 vocabulary of 10 is untouched). Any
  recompute path may refresh them freely.
- **Consequence:** `guards.py` byte-unchanged; `state_machine.py` byte-unchanged
  (Module 8 adds no transition). `alembic head` → `0017_recovery_score`.
- **Status:** IN FORCE

## D-110 — Warm-start normalisation: a linear map of `promise_keeping_rate` onto the cap band
- **Milestone:** Module 8
- **Decision:** §8.2 says `adjusted = base × normalized promise_keeping_rate`,
  "capped at 0.5×–1.3×", without giving the normalisation. What is it?
- **Chosen:** `multiplier = cap_low + promise_keeping_rate × (cap_high − cap_low)`
  = `0.5 + rate × 0.8`, then clamped to `[cap_low, cap_high]`
  (`PolicyConfig.warm_start_cap_low` / `_high`, defaults 0.5 / 1.3). So
  `rate 0.0 → ×0.5` (exact lower cap), `rate 1.0 → ×1.3` (exact upper cap),
  `rate ≈ 0.625 → ×1.0` (break-even), and a missing `promise_keeping_rate`
  (`None` — no relationship history) → `×1.0` exactly (base used unchanged). The
  clamp additionally defends against an out-of-range stored rate. The final
  probability is `min(1, max(0, base × multiplier))`, quantised to 5 dp — bounded
  and deterministic.
- **Alternatives:** `multiplier = rate` directly (rejected — a "good" rate of
  0.9 would only ever *reduce* the probability, contradicting §8.2's "strong
  history lifts it"); `rate / population_baseline` (rejected — needs a baseline
  figure the project does not have, and Torque has no resolved-outcome history
  yet); replacing the cold-start number outright with a history-derived one
  (rejected by §8.2 itself — capping keeps cold-start and warm-start cases on a
  comparable scale).
- **Reasoning:** the linear map is the simplest normalisation that (a) makes the
  named caps the exact images of `rate ∈ {0, 1}`, (b) is monotone in the rate,
  (c) needs no external constant, (d) is trivially bounded and testable. It is a
  **stated default**, not derived from Torque data — the same status Part E item
  12 already gives the 0.5 / 1.3 caps themselves (see U-09).
- **Consequence:** `amount_bucket` is retained in the lookup *signature*
  (Decision F names it) but seeds **no** probability variation — every Decision F
  benchmark is leg × time only. The dimension is surfaced in the breakdown (a
  grouping label + the §8.4 feature set) and is otherwise inert.
- **Status:** IN FORCE

## D-111 — Forward cost = next-step channel rate-card sum; zero / unpriced / absent cost floors the divisor
- **Milestone:** Module 8
- **Decision:** §8.2 — `cost` = Σ `ChannelRateCard.rate_per_unit` for "the
  channel(s) the assigned playbook's next likely step would use". Which step is
  "next likely", and what happens when the sum is zero / unknown (so
  `(p × amount) ÷ cost` would divide by zero)?
- **Chosen:**
  - **Next likely step** = the node at the case's live `PlaybookRun.active_step_id`
    (`RUNNING`), which is exactly the node `runner.execute_due_job` will execute
    next (`next_step_source = LIVE_RUN`). No live run yet but the case is
    diagnosed → the *candidate* playbook from
    `torque.policy.selection.select_playbook_id` and its **entry** node
    (`CANDIDATE_PLAYBOOK`) — this keeps the cost meaningful the moment diagnosis
    completes, before Module 4's run-instantiation is wired (D-093). Neither
    (a brand-new `DETECTED` case) → `NONE`.
  - **Channels** via `torque.execution.executor.channel_for` — `RETRY_PAYMENT`
    / `ESCALATE_HUMAN` / `LOG_PROMISE` carry none; `GENERATE_PAYMENT_LINK` maps
    to `"payment_link"`, which has no seeded `ChannelRateCard` row.
  - **Zero / unpriced / absent cost** → the divisor **floors** at
    `PolicyConfig.recovery_score_cost_floor` (default ₹0.01 — one paisa,
    ≈ the cheapest real channel). `cost_basis` records which: `PRICED` (a real
    rate drove it — its sum may still be < the floor, e.g. a rate of 0),
    `FLOOR_NO_CHANNEL` (a retry — no channel to price), `FLOOR_UNPRICED_CHANNEL`
    (`payment_link` / a missing rate-card row), `FLOOR_NO_PLAYBOOK` (pre-diagnosis).
- **Alternatives:** treat a missing cost as "free" and let the score go to
  +∞/NaN (rejected — a `ZeroDivisionError`, and it would let an *absence of
  information* dominate the queue); skip / null the score (rejected — §8.5
  demands a score for every open case incl. at creation); a large constant
  (rejected — arbitrary, and it would wrongly *sink* free next steps).
- **Reasoning:** the blueprint is silent on zero cost, so the **conservative**
  behaviour (task instruction) is chosen: keep the score finite, comparable, and
  honest about its basis. A genuinely free next step (a retry) still ranks
  highest — just finitely — which is correct resource-aware prioritisation.
- **Consequence:** `PolicyConfig.recovery_score_cost_floor` added (not a
  blueprint figure — the conservative default). No division by zero is
  structurally possible: `effective_cost ≥ floor > 0` always.
- **Status:** IN FORCE

## D-112 — Recompute triggers: inline for creation / diagnosis, one Celery-beat entry for daily
- **Milestone:** Module 8
- **Decision:** §8.5 — recompute on (1) case creation, (2) diagnosis completion,
  (3) daily for open cases. How, without a second scheduler?
- **Chosen:**
  - **(1) + (2) inline** — `torque.scoring.score.score_case(session, case)` is
    called at the end of each leg's ingestion path
    (`ingestion.cases` / `checkout` / `subscription` / `b2b`) and at the end of
    `diagnosis.engine._apply_result`, **in the same transaction**. It writes only
    the three derived columns — no `CaseEvent`, no status change — so it does not
    disturb any tested post-ingestion / post-diagnosis contract (cases still end
    `DETECTED` / route the same way).
  - **(3) daily** — `torque.scoring.tasks.recompute_open_case_scores_task` on the
    existing Celery app, wired as one `beat_schedule` entry
    (`crontab(hour=2, minute=0)`) in `torque.ingestion.celery_app`. It re-scores
    every open case and refreshes any `human_queue` entry's stored `priority`.
  - `recompute_recovery_score_task(case_id)` is also provided as the reusable
    single-case entry point.
- **Alternatives:** enqueue a task per case-creation / diagnosis (rejected —
  would run diagnosis-time scoring out-of-band and, in eager test mode, change
  the tested synchronous contract, the exact reason D-080 / D-093 deferred the
  *status-changing* inter-module dispatch); a new APScheduler / cron process
  (rejected — "do not create a second scheduling architecture").
- **Reasoning:** the deferral precedent (D-080 / D-093) is about **status /
  side-effecting** orchestration; a derived-column write is safe to wire inline,
  and §8.5 explicitly requires all three triggers.
- **Consequence:** `ingestion/{cases,checkout,subscription,b2b}.py` and
  `diagnosis/engine.py` each gain one `score_case(...)` call;
  `ingestion/celery_app.py` gains one beat entry + the `torque.scoring`
  autodiscover/import.
- **Status:** IN FORCE

## D-113 — The `priority()` seam becomes `(session, case)` and returns the real score; Module 6 placeholder assertions updated
- **Milestone:** Module 8
- **Decision:** D-098 reserved `torque.coordination.outreach_coordinator.priority()`
  as the one-function Module 8 seam ("Module 8 replaces only this function
  body"). Module 8's score needs the DB session (promise-keeping history, rate
  card, the case's next playbook step) — the placeholder took only `case`.
- **Chosen:** `priority(session, case) -> Decimal` now delegates to
  `torque.scoring.compute_recovery_score(session, case).score` — the single
  implementation of the formula. The two callers are updated:
  `human_queue.enqueue` → `_priority(session, case)`;
  `merge._ordered(session, items)`. No consumer re-derives the formula (a
  structural test asserts `human_queue` / `merge` never import
  `compute_recovery_score` / `benchmarks` / `cost`). `HumanQueueEntry.priority`
  (`NUMERIC(14,2)`, migration 0016) is unchanged — it stores the score at
  enqueue time; the daily sweep (D-112) refreshes it in place. Three Module 6
  tests that pinned the `amount_at_risk` placeholder value
  (`test_enqueue_defaults_priority_to_*`, `test_broken_promise_routes_*`,
  `test_priority_is_amount_at_risk_placeholder`) are updated to assert the real
  score — analogous to Module 7 inverting three state-machine tests.
- **Alternatives:** keep `priority(case)` and thread the session another way
  (rejected — a hidden global/session-registry is worse than an explicit
  parameter); a second `priority_scored(session, case)` alongside the old one
  (rejected — two seams, drift).
- **Consequence:** all accepted Module 6 *behaviour* is preserved (queue ordered
  by economic score, FIFO tie-break, idempotency, tenancy, merge primary =
  higher score); only the score's *value* changes, which is the sanctioned
  Module 8 deliverable.
- **Status:** IN FORCE

---

## D-114 — Module 9 is a pure read/derive layer; no persisted aggregate, no migration
- **Milestone:** Module 9 — Reporting & Measurement
- **Decision:** Does reporting materialise metrics into a rollup / snapshot
  table, or derive them on demand from the domain tables?
- **Chosen:** **Derive on demand.** New package `torque.reporting`
  (`metrics.py` — the aggregation functions; `schemas.py` — the pydantic
  result/response contract) + a read-only `torque.api.reporting` router. Every
  figure is computed live from `revenue_leak_case`, `action` / `action_case`,
  `b2b_invoice`, `case_event`, `human_queue`. **No new table, no enum, no
  `CaseEventType`, no column, no migration** — `alembic head` stays
  `0017_recovery_score`.
- **Alternatives:** a `metric_rollup` table refreshed by a Celery beat job
  (rejected — §9.8: "avoid a reporting table that becomes an unexplained source
  of truth"; a cache needs refresh semantics, idempotency guarantees, and a
  double-count story it does not need at demo scale); a materialised view
  (Postgres-specific, same staleness question).
- **Reasoning:** §9.8 prefers derivation; §9.11 says do not build a warehouse. A
  reported number is then always exactly what the live rows say and is traceable
  straight through case → actions → `CaseEvent` stream. The summary path
  materialises the in-window case rows and aggregates in the service layer —
  O(cases-in-window) memory; a SQL `GROUP BY` rewrite (and a
  `(merchant_id, closed_at)` index) is the first, cheapest optimisation if a
  merchant ever exceeds ~10k open cases. Documented, not built.
- **Consequence:** `state_machine.py` / `guards.py` byte-unchanged; Module 9
  adds zero write paths (a structural test asserts the router is GET-only).
- **Status:** IN FORCE

## D-115 — "revenue at risk" per case: `amount_at_risk` for non-B2B, `Σ B2BInvoice.original_amount` for B2B
- **Milestone:** Module 9
- **Decision:** The recovery-rate denominator. `RevenueLeakCase.amount_at_risk`
  is immutable for three legs but a **mutating residual** for B2B (it decrements
  as partial payments land — INV-55), and a B2B case settled in one payment can
  even be left holding its *original* value (Module 7's full-settlement path does
  not re-zero it). So `SUM(amount_at_risk)` is not a reliable "total at risk".
- **Chosen:** per case — non-B2B → `amount_at_risk`; B2B → `Σ B2BInvoice.
  original_amount` for the case (immutable; the invoice table is authoritative
  for B2B amounts). A B2B case with no invoice rows contributes its
  `amount_at_risk`. `revenue_at_risk` (report) is the sum over in-scope cases.
- **Alternatives:** `amount_at_risk + COALESCE(recovered_amount, 0)` (rejected —
  double-counts the single-payment B2B case and every `CANCELLED` self-paid
  case); fixing Module 7's B2B residual (out of scope — do not modify Module 7).
- **Consequence:** the summary and `by_leg` amount fields reconcile exactly
  (`Σ by_leg == summary`); B2B `recovered_amount` can be reported even when
  `amount_at_risk` reads 0.
- **Status:** IN FORCE

## D-116 — "recovered" = Torque-credited only; `SELF_RECOVERED` reported separately, never folded in
- **Milestone:** Module 9
- **Decision:** Which recoveries count toward the headline number?
- **Chosen:** `recovered_amount` sums `recovered_amount` where
  `recovery_type IS NOT NULL AND recovery_type != 'SELF_RECOVERED'` (Blueprint
  §9.1 verbatim — i.e. `AGENT_ASSISTED` or `AMBIGUOUS`). `SELF_RECOVERED` money
  is reported as a **separate** `self_recovered_amount` field and never added to
  `recovered_amount`. Reconciliation (Module 7) is the sole authority for
  `recovery_type` / `recovered_amount`; Module 9 never re-matches a payment or
  re-derives credit (§9.3 / INV-53).
- **Reasoning:** the north-star is *money Torque brought back* (§9.1 outcome-
  based). Reporting the self-recovered figure alongside is the honest-reporting
  differentiator, not a number to hide or inflate.
- **Status:** IN FORCE

## D-117 — recovery rate is reported both by count (blueprint-literal) and by amount (demo headline)
- **Milestone:** Module 9
- **Decision:** §9.1 defines "Recovery rate by leg" as *recovered cases ÷ total
  cases*; the §9.4 demo headline (43.7% = ₹52.4L ÷ ₹1.20 Cr) is money-weighted.
- **Chosen:** expose both, labelled. `recovery_rate` = `recovered_case_count ÷
  case_count` (the §9.1 definition, canonical). `amount_recovery_rate` =
  `recovered_amount ÷ revenue_at_risk`. Zero cases / zero risk → the respective
  rate is `Decimal(0)`, never a division error. `recovered_case_count` counts
  `status = 'RECOVERED'` **and** Torque-credited; a B2B `PARTIALLY_RECOVERED`
  case is not a "recovered case" (still open) but its banked partials **do**
  appear in `recovered_amount` — the two figures reconcile by design.
- **Status:** IN FORCE

## D-118 — "unresolved" / "blocked amount" / "deferred amount" / "escalated" definitions
- **Milestone:** Module 9
- **Decision:** §9.2 lists these without formulas.
- **Chosen:**
  - **unresolved case** = `status NOT IN ('RECOVERED', 'CANCELLED', 'WRITTEN_OFF')`
    and not a non-B2B `PARTIALLY_RECOVERED` (terminal). So: every open state
    **plus `EXHAUSTED`** (automation gave up, no human, no money) **plus B2B
    `PARTIALLY_RECOVERED`** (still dunning). `WRITTEN_OFF` and self-paid
    `CANCELLED` are *resolved*. `unresolved_amount` = Σ current `amount_at_risk`
    of those (the live residual exposure). `exhausted_case_count` /
    `partially_recovered_case_count` are informational sub-counts.
  - **blocked amount** = Σ `revenue_at_risk` (D-115) of cases with ≥1 `Action`
    whose `outcome = 'BLOCKED_BY_GUARDRAIL'` — deduped per case (a case counts
    once). Zero when there are none ("where applicable").
  - **deferred amount / count** = same, for `block_reason =
    'OUTREACH_COORDINATOR_DEFERRED'` — the only defer that writes an `Action`
    (D-099). A pure timing defer (quiet hours, UPI peak) writes **no row** and is
    not countable from `Action`; documented as a known limitation of the source
    data, not a Module 9 gap.
  - **escalated case** = `status = 'ESCALATED_TO_HUMAN'` **∪** present in
    `human_queue` (deduped). The queue also holds broken-promise / open-
    conversation cases not in that status. `escalations_by_reason` is grouped
    from `human_queue.reason`.
- **Consequence:** case buckets partition the total:
  `recovered + self_recovered + written_off + unresolved(incl. exhausted & B2B
  partial) == case_count`.
- **Status:** IN FORCE

## D-119 — "recovery over time" buckets on `closed_at` (UTC), half-open windows
- **Milestone:** Module 9
- **Decision:** which date column, which timezone, which window semantics for the
  time series (vs. the `opened_at` window that defines a *batch*).
- **Chosen:** `date_trunc(bucket, closed_at)` with `bucket ∈ {day, week, month}`,
  `closed_at` in **UTC** (project storage convention — every timestamp column is
  `DateTime(timezone=True)` stored UTC; IST localisation is a UI / Module 10
  concern). Only Torque-credited `RECOVERED` cases contribute (D-116); a case
  with `closed_at IS NULL` (open, or a B2B partial) never appears — its money is
  in the summary `recovered_amount`, and lands in a bucket when the case finally
  closes. The window is half-open `[from, to)` so adjacent windows partition the
  recoveries with no boundary double-count. The batch window (`opened_at`) and
  the time-series window (`closed_at`) are exposed as **separate** query params
  (`opened_from`/`opened_to` vs `closed_from`/`closed_to`) so the two are never
  confused.
- **Status:** IN FORCE

## D-120 — "recovery by intervention" = two orthogonal groupings (by leg, by action type)
- **Milestone:** Module 9
- **Decision:** §9.1 groups "₹ recovered **by leg**"; §9.5 wants comparison
  across **intervention types** (payment retry, outreach, …). Same thing or two?
- **Chosen:** two views. `by_leg` (grouping on `leg_type`) is **primary** and
  provides the §9.5 intervention-effectiveness columns
  ({cases_attempted, cases_recovered, revenue_at_risk, recovered_amount,
  recovery_rate}); its amount totals reconcile with the summary.
  `by_action_type` is a **secondary** view — for each `ActionType` Torque
  *executed*, the distinct cases that used it, of which recovered, and their
  amounts. A case that used both a retry and a WhatsApp send appears in **both**
  rows, so `by_action_type` rows sum to more than the de-duplicated totals
  (stated in the schema docstring). `cases_attempted` in `by_leg` = every
  in-scope case of that leg ("cases analysed"); in `by_action_type` = cases with
  ≥1 executed action of that type.
- **Status:** IN FORCE

## D-121 — incrementality lift / Wilson CI / SUTVA-adjusted lift are DEFERRED (intentional deviation from §9.1 as written)
- **Milestone:** Module 9
- **Decision:** Blueprint §9.1 lists "Incrementality lift" (with a Wilson score
  CI) and "SUTVA-adjusted lift" in the Module 9 dashboard-metrics table. Are
  they in this run?
- **Chosen:** **No — deferred.** The maintainer's Module 9 instructions scope
  this run to **descriptive** recovery reporting and explicitly separate it from
  "incremental causal impact measurement" (§9.6), with the scope-boundary list
  naming "SUTVA analysis" and "confidence intervals" as not-to-implement.
  Module 9 reports *what happened*; the causal/experimental layer
  (incrementality lift, Wilson interval, the cross-merchant SUTVA footnote) is a
  later scope — provisionally "Module 9b — Incrementality" (see U-10).
- **Reasoning:** an intentional, documented deviation from the blueprint *as
  written* (§9.1), made because the two instruction sources conflict and the
  maintainer's direct instruction governs. The
  `Merchant_Counterparty.in_control_cohort` / `RevenueLeakCase.control_group`
  data those metrics need is already collected (Modules 1/2) and is **left
  untouched** — the deferred work needs no schema change, only a new consumer.
- **Consequence:** the Module 9 API surface carries no lift / CI / SUTVA
  endpoint; `learning_log.md` §15 states plainly that Module 9 does not prove AI
  causality.
- **Status:** IN FORCE

---

## D-122 — Module 10 UI: a static SPA served by FastAPI, one process, no build step
- **Milestone:** Module 10 — UI/UX
- **Decision:** The repo has no frontend and no Node toolchain (§10.14: "choose
  the simplest free-tier stack ... avoid unnecessary infrastructure ... runnable
  with a straightforward command"). What stack?
- **Chosen:** A **hand-written static single-page app** — one `index.html` + one
  `torque.css` + one `torque.js` (vanilla, no framework, no bundler) under
  `src/torque/ui/static/`, mounted with `StaticFiles` at `/ui` by the **same**
  `create_app()` FastAPI app. `GET /` redirects to `/ui/`. The whole product
  runs with the existing `uv run python -m torque` on one port. Hash routing
  (`#/dashboard`, `#/cases/<id>`, `#/console`, `#/demo`). No new runtime
  dependency (Starlette's `StaticFiles` ships with FastAPI; `jinja2` is **not**
  added).
- **Alternatives:** a React/Vite/TS SPA (rejected — a whole Node toolchain,
  `npm install`, a second dev server, a build artefact — exactly the
  "unnecessary infrastructure" §10.14 warns against for a Python-only backend);
  server-rendered Jinja templates (rejected — adds `jinja2`, and a static SPA
  polls the JSON API just as easily).
- **Consequence:** "frontend lint / typecheck / build" is **N/A** — there is no
  TS to typecheck and no build; `ruff` covers the Python view/route code, and
  the templates are static text. The DOM logic is verified through the API
  contract it depends on plus shell-and-wiring assertions
  (`tests/test_module10_ui.py`), not a browser harness.
- **Status:** IN FORCE

## D-123 — Agent Console human resolution: reuse the existing `→ {RECOVERED, PARTIALLY_RECOVERED, WRITTEN_OFF}` edges; add `human_resolution_writer` to `guards.py`; migration 0018
- **Milestone:** Module 10
- **Decision:** §10.8 assigns the Agent Console the `escalation_resolution`
  write-back and the `HUMAN_RESOLVED` event. What changes are needed?
- **Chosen:**
  - **`state_machine.py` — UNCHANGED.** The `ESCALATED_TO_HUMAN → {RECOVERED,
    PARTIALLY_RECOVERED, WRITTEN_OFF}` edges are already legal (§4 diagram,
    present since M1); pause/unpause use the existing `PLAYBOOK_ACTIVE ↔ PAUSED`.
    No Module 10 transition is required.
  - **`HUMAN_RESOLVED` — UNCHANGED.** The `CaseEventType` and its
    `{resolution, agent_id}` payload schema already exist (M1). `CaseEventType`
    count stays 10.
  - **Migration `0018_escalation_resolution`** — three nullable columns on
    `revenue_leak_case`: `escalation_resolution` (`VARCHAR(64)` — the label:
    `RECOVERED_BY_HUMAN` / `PARTIALLY_RECOVERED_BY_HUMAN` / `WRITTEN_OFF`, an
    `EscalationResolution` StrEnum owned in `torque.agent_console`, not a PG
    enum), `escalation_resolved_by`, `escalation_resolved_at`. Unguarded (like
    `root_cause_code`).
  - **`guards.py` — CHANGED (explicitly required, reported).** A recovering
    resolution must record `recovered_amount` and `recovery_type = AGENT_ASSISTED`
    (the human agent is Torque's — so it counts in Module 9's `recovered_amount`,
    D-116), and those two fields are `module7_writer`-guarded. Added
    `human_resolution_writer(session)` + an `hr` flag threaded into `_guard_case`
    (`not (m7 or hr)`), mirroring `network_directive_writer` exactly. ~10 lines.
    Reconciliation keeps its own gate; this is a second deliberate entry point,
    not a widening of Module 7.
- **Alternatives:** reuse `module7_writer` from the console (rejected —
  misrepresents authorship: its docstring says "Module 7 is the only code that
  should ever enter this"); leave `recovery_type` NULL on a human recovery and
  special-case NULL in Module 9's `recovered_amount` predicate (rejected —
  hackier, and it edits accepted Module 9 metric semantics for a new path).
- **Consequence:** `guards.py` `git diff HEAD` is non-empty for the first time
  since M6a — exactly the `human_resolution_writer` addition. `state_machine.py`
  stays byte-stable.
- **Status:** IN FORCE

## D-124 — Module 10 backend additions: read endpoints on the Module 9 router; a small Agent Console + Demo surface; no business logic in routes
- **Milestone:** Module 10
- **Decision:** §10.13 — add backend endpoints only where Module 10 needs
  something not already exposed; keep domain logic in the modules.
- **Chosen:**
  - **`torque.reporting`** gains `top_at_risk_cases` (§10.4 — open cases
    `ORDER BY recovery_score DESC NULLS LAST`, the frontend never re-derives the
    formula), `human_queue_list` (§10.7 — `human_queue` rows joined to the case,
    ordered by the entry's stored `priority` — the Module 8 seam), and
    `recent_activity` (§10.17 — recent `CaseEvent`s across the merchant, newest
    `event_seq_id` first). `case_detail` gains `recovery_score_breakdown` +
    `recovery_probability` (Module 8's stored §8.7 structure, surfaced verbatim
    for the "WHY THIS CASE?" panel) + `counterparty_label` + `root_cause_code`.
    All still `GET`, all tenant-scoped (INV-58 extended).
  - **`torque.agent_console`** — a new package: `resolve_escalation` /
    `pause_case` / `unpause_case`, exposed as three `POST`
    `/agent-console/{merchant_id}/cases/{case_id}/{resolve|pause|unpause}`
    endpoints (`torque.api.agent_console`). Domain logic in the package; the
    router only maps HTTP ↔ the call and errors to codes
    (`CaseNotFoundError` → 404, `HumanResolutionError` → 409).
  - **`torque.demo`** — `seed_demo` (§10.16 deterministic dataset) + `scenarios`
    (§10.10 one-click injectors composing the *existing* ingestion / compliance
    code), exposed as `POST /demo/seed`, `GET /demo/scenarios`,
    `POST /demo/inject/{key}`, `GET /demo/merchant`.
- **"cancel"** (§10.8) maps to **resolve → `WRITTEN_OFF`** (the "give up"
  terminal) for an escalated case; there is deliberately no
  `ESCALATED_TO_HUMAN → CANCELLED` (the blueprint reserves CANCELLED /
  `SELF_RECOVERED` for genuine customer self-payment via reconciliation). The
  three controls surfaced are therefore **pause / unpause / resolve{recover,
  partial, write-off}**.
- **Live updates (§10.17):** **polling** — `torque.js` GETs `/reports/{m}/activity`
  every 3 s on the demo page. No WebSocket: the backend has no push channel and
  the blueprint says use the simplest reliable mechanism.
- **Status:** IN FORCE

## D-125 — Demo `reset` disables the `case_event` append-only trigger for the wipe
- **Milestone:** Module 10
- **Decision:** `POST /demo/seed?reset=true` must clear the demo merchant's data
  to rebuild deterministically, but `case_event` has a Postgres `BEFORE DELETE`
  trigger (`case_event_no_mutate`, migration 0005) that rejects **any** delete,
  raw SQL included.
- **Chosen:** `_wipe` runs `ALTER TABLE case_event DISABLE TRIGGER
  case_event_no_mutate`, deletes the demo merchant's rows in FK order, then
  `ENABLE TRIGGER` — all in the seed's transaction (a rollback reverts both;
  needs table ownership, which the app/migration user has). Scoped strictly to
  `merchant_id = 'acc_demo'`. Without `reset`, `seed_demo` is a no-op if already
  seeded (idempotent). The production append-only guarantee for real merchants
  is untouched — this is an explicit, demo-only, single-merchant reset.
- **Alternatives:** `session_replication_role = replica` (rejected — needs
  superuser); never support reset, require a full DB drop to reseed (rejected —
  poor demo ergonomics); make every seeded row deterministically keyed and
  upsert (rejected — a large rewrite of the seed for marginal benefit).
- **Status:** IN FORCE

## D-126 — Backend language/framework is Python (Part D item 2 / U-05), decided-by-implementation
- **Milestone:** Module 11
- **Decision:** Blueprint Part D item 2 ("backend language/framework was never
  chosen") is the one open item in the Module 11 scope. Pick it now.
- **Chosen:** **Python** — recorded explicitly, not as a new choice but as the
  one the repository has been committed to since M1 (SQLAlchemy 2.0, Pydantic v2,
  Alembic, Celery, FastAPI, pytest — no Node anywhere). The blueprint's
  "Pydantic (Python) or Zod (TypeScript)" fork resolves to Pydantic; the
  Temporal-SDK-language question is moot while Temporal is not implemented
  (D-090 / D-127).
- **Alternatives:** TypeScript/Node (would require rewriting the entire
  codebase); Go/Java (never in play).
- **Reasoning:** Making the de-facto choice explicit closes Part D item 2 so a
  future contributor does not treat the language as still-open. Nothing in the
  system now depends on the choice being re-litigated.
- **Consequence:** U-05's language/framework sub-item is resolved. Build tooling
  (`uv`, the lockfile-reproducible Docker image) is Python-native.
- **Status:** IN FORCE

## D-127 — No Temporal in Module 11; Postgres-polling stays; Temporal is a documented future driver-swap only
- **Milestone:** Module 11
- **Decision:** Blueprint Module 11's table lists "Temporal (OSS, self-hosted)
  for `PlaybookRun`; Postgres-polling fallback if infeasible". Does Module 11
  stand up a Temporal cluster / add the SDK?
- **Chosen:** **No.** D-090 (Postgres-polling chosen over Temporal, Module 5)
  **remains IN FORCE**. Module 11 adds no Temporal dependency, no Temporal
  container, and does not reopen the decision. The `execute_due_job` tick +
  `scheduled_job` table stay the durable execution mechanism; Temporal is
  mentioned in `ARCHITECTURE.md` only as a possible future driver swap behind
  that same seam.
- **Alternatives:** stand up self-hosted Temporal now (rejected — the fallback
  is built, working, and tested; a cluster is real operational weight for no
  demo-scope benefit; Part E item 8's go/no-go stays "no").
- **Reasoning:** The maintainer's Module 11 instructions lock this. Blueprint
  Part E already frames Temporal go/no-go as non-blocking with a working
  fallback in place.
- **Consequence:** `DEFERRED.md` keeps "real Temporal engine" as an explicit
  future (🔮) item. No `pyproject.toml` / compose change toward Temporal.
- **Status:** IN FORCE

## D-128 — One reusable application image for api / worker / beat
- **Milestone:** Module 11
- **Decision:** Package the three Python processes (FastAPI API, Celery worker,
  Celery beat) as one image or three?
- **Chosen:** **One `Dockerfile`** → image `torque-app:local`, reused by all
  three compose services, which differ only by their `command:` (`python -m
  torque` / `celery … worker` / `celery … beat`). `uv sync --frozen` installs
  from `uv.lock` for reproducibility; non-root `USER torque`; runtime deps only
  (`--no-dev`).
- **Alternatives:** three Dockerfiles (rejected — identical dependency closures,
  triple the build/maintenance surface); a `pip install .` without the lockfile
  (rejected — not reproducible; `uv.lock` is committed for exactly this).
- **Reasoning:** The maintainer's Module 11 instruction: "reuse the same Python
  application image/code where practical rather than creating unnecessary
  duplicated Dockerfiles."
- **Consequence:** `Dockerfile` + `.dockerignore` added. `beat` runs with
  `--schedule=/tmp/celerybeat-schedule` because the image's working dir is
  read-only to the non-root user.
- **Status:** IN FORCE

## D-129 — docker-compose profiles: bare `up` = infra only; `--profile full` = whole runtime
- **Milestone:** Module 11
- **Decision:** Adding `api`/`worker`/`beat` to compose must not break the
  existing host dev loop (`docker compose up -d db` + `uv run python -m torque`).
- **Chosen:** `db` and `redis` carry **no** `profiles:` key, so a bare
  `docker compose up` still starts only the infrastructure. `migrate`, `api`,
  `worker`, `beat` sit behind `profiles: ["full"]` — `docker compose --profile
  full up` brings the whole containerised runtime.
- **Alternatives:** put everything in the default set (rejected — every bare
  `up` would build the image and run 4 extra containers, breaking the
  lightweight loop); a second compose file (rejected — drift risk, more to keep
  in sync).
- **Reasoning:** Satisfies both "reproduce the real runtime" and "the demo /
  dev loop still starts simply".
- **Status:** IN FORCE

## D-130 — Schema is applied by a one-shot `migrate` service the app services depend on
- **Milestone:** Module 11
- **Decision:** How does the containerised runtime reach `alembic upgrade head`
  before the app starts?
- **Chosen:** A `migrate` service (`command: alembic upgrade head`,
  `restart: "no"`) that runs once and exits; `api`, `worker`, and `beat`
  `depends_on: { migrate: { condition: service_completed_successfully } }` (and
  `db` / `redis` healthy). No app process runs migrations itself.
- **Alternatives:** each service runs `alembic upgrade head` in its entrypoint
  (rejected — three concurrent upgraders racing on first boot); a manual
  out-of-band step (rejected — defeats "reproducible from the repo alone");
  migrations on FastAPI startup (rejected — `create_app()` is deliberately
  side-effect-free, M7a).
- **Consequence:** Exactly one upgrade per `up`; `migrate` exits 0 and the
  others proceed.
- **Status:** IN FORCE

## D-131 — `Settings` owns the API bind address; `__main__` stops reading `os.environ`
- **Milestone:** Module 11
- **Decision:** `src/torque/__main__.py` read `TORQUE_API_HOST` / `TORQUE_API_PORT`
  directly from `os.environ`; every other config value goes through
  `torque.config.Settings`. Make it coherent.
- **Chosen:** Add `Settings.api_host` (default `127.0.0.1`) and
  `Settings.api_port` (default `8000`), each with
  `validation_alias=AliasChoices("<field>", "TORQUE_API_<HOST|PORT>")` so the
  established `TORQUE_API_*` env names keep working. `__main__.main()` now reads
  `get_settings().api_host / .api_port`. Behaviour and defaults are identical;
  the compose `api` service sets `TORQUE_API_HOST=0.0.0.0`.
- **Alternatives:** leave `__main__` reading `os.environ` (rejected — the one
  config value not flowing through `Settings`); rename the env vars to
  `API_HOST` / `API_PORT` (rejected — `TORQUE_`-prefixed is the house
  convention: `TORQUE_POLICY_*`, `TORQUE_ALEMBIC_URL`, `TORQUE_TEST_ADMIN_URL`).
- **Status:** IN FORCE

## D-132 — Minimal readiness endpoint `GET /health/ready`; `/health` unchanged; no observability stack
- **Milestone:** Module 11
- **Decision:** `GET /health` is a static liveness probe. Does Module 11 need a
  readiness check, and how much?
- **Chosen:** Add **`GET /health/ready`** in `torque.api.health` — a `SELECT 1`
  against Postgres and a 1-second-timeout `PING` against the Redis broker;
  `200 {"status":"ready","checks":{…}}` when both answer, `503 {"status":"not
  ready", …}` naming the failed component otherwise. `GET /health` keeps its
  exact Milestone-7a contract (`200 {"status":"ok"}`). The compose `api`
  healthcheck probes `/health/ready`. **Nothing else** — no Prometheus, Grafana,
  ELK, OpenTelemetry, tracing, or structured-log shipping.
- **Alternatives:** no readiness endpoint (rejected — compose needs a real
  "is the API wired to its infra" signal to gate `depends_on` / show healthy);
  a deep dependency graph / metrics surface (rejected — explicitly out of scope,
  free-tier, minimal-operability instruction).
- **Consequence:** `torque.api.app` includes a `health_router` (the inline
  `/health` moved into it verbatim); `redis` (already a dependency) is imported
  lazily inside the probe. The two probe functions are module-level so tests can
  substitute them without a live Redis.
- **Status:** IN FORCE

## D-133 — Incrementality recovery is intent-to-treat (`status ∈ {RECOVERED, CANCELLED}`), not the attributed descriptive rate
- **Milestone:** Module 9b
- **Decision:** Blueprint §9.1 defines incremental lift as "treatment recovery
  rate − control recovery rate". Which "recovery"? Module 9's descriptive
  `recovery_rate` counts a case only if `status = RECOVERED` **and** the recovery
  is Torque-attributed (`recovery_type != SELF_RECOVERED` — D-116).
- **Chosen:** For the **causal** layer, a case counts as recovered iff its
  status is `RECOVERED` **or** `CANCELLED` (customer self-paid) — **intent-to-
  treat, attribution-agnostic**. The descriptive `recovery_rate` (D-116) is
  **unchanged**; this is a second, clearly-labelled definition used only by
  `torque.reporting.incrementality`, surfaced in the API as `recovery_definition`
  and in the UI beside the number.
- **Alternatives:** reuse Module 9's attributed `is_recovered_case` verbatim
  (rejected — a held-out control case that recovers does so by self-payment, so
  its `recovery_type` is `SELF_RECOVERED`; an attributed definition pins the
  control rate at ~0 and "lift" collapses into "treatment rate", which is not a
  causal comparison and contradicts Blueprint §6's own reasoning about
  non-trivial control recovery rates); count `PARTIALLY_RECOVERED` too (rejected
  — not a full binary success; conservative to exclude, matching Module 9).
- **Consequence:** `_RECOVERED_STATUSES = {RECOVERED, CANCELLED}` in
  `incrementality.py`. `WRITTEN_OFF` / `EXHAUSTED` / `PARTIALLY_RECOVERED` / open
  statuses are non-recoveries in both arms. Cohort membership is the per-case
  `RevenueLeakCase.control_group` snapshot (`True` control / `False` treatment /
  `None` excluded); no new cohort-assignment mechanism, no schema change.
- **Status:** IN FORCE

## D-134 — Wilson score interval per cohort; Newcombe (1998) hybrid for the difference; 95% two-sided
- **Milestone:** Module 9b
- **Decision:** Blueprint §9.1 mandates "a Wilson score confidence interval …
  a naive normal-approximation interval can produce nonsensical bounds at
  demo-scale sample sizes" but names no confidence level and no method for the
  *difference* of two proportions.
- **Chosen:**
  - Each cohort proportion: the **Wilson score interval**, clamped to `[0, 1]`.
  - The lift (treatment rate − control rate): **Newcombe's (1998) hybrid score
    interval** ("method 10") — `d ∓ √((p̂₁−l₁)² + (u₂−p̂₂)²)` etc. built from the
    two Wilson intervals — clamped to `[-1, 1]`. This is the standard
    Wilson-based CI for a difference of independent proportions and stays in
    range at tiny `n`.
  - **95% two-sided**, `z = Φ⁻¹(0.975) ≈ 1.959963984540054` (`statistics.
    NormalDist().inv_cdf(0.975)` — stdlib, no new dependency). The conservative,
    universally-understood reporting default; a wider batch simply yields a
    wider interval, shown honestly. `confidence_level` and `z_value` are in the
    response.
  - `total == 0` → `rate` / bounds are `null` (never `NaN` / `inf`); the
    difference interval is `null` when either cohort is empty.
  - All arithmetic in `Decimal` (`.sqrt()`), outputs quantised to 4 dp
    (`ROUND_HALF_EVEN` — Module 9's rate quantum).
- **Alternatives:** Wald/normal interval (rejected — the Blueprint forbids it);
  Agresti–Caffo for the difference (defensible, but Newcombe pairs directly with
  the mandated Wilson and is the more common companion); 90% or 99% level
  (rejected — 95% is the expected default and the honest-width argument applies
  at any level).
- **Consequence:** `wilson_interval` / `newcombe_difference` in
  `torque.reporting.incrementality`, covered by `tests/test_module9b_wilson.py`
  (zero/all successes, one observation, tiny cohorts, equal rates, ± lift — no
  invalid bound ever).
- **Status:** IN FORCE

## D-135 — The deterministic demo seed assigns cohorts and adds a second merchant so the SUTVA number is live
- **Milestone:** Module 9b
- **Decision:** The `acc_demo` seed created `Merchant_Counterparty` rows with no
  cohort (`in_control_cohort` NULL), so the incrementality card would always be
  empty and the SUTVA-adjusted lift would always equal the headline.
- **Chosen:** The seed now (a) assigns every demo counterparty a cohort via the
  **existing** `MerchantCounterparty.assign_cohort` (3 of 16 held out as control,
  ~19% — near the Blueprint's 10–15% holdout; `cohort_assigned_at` pinned to the
  fixed demo clock for a byte-identical rebuild), and (b) adds a small companion
  merchant **`acc_demo_up`** that is *treating* two of those three control
  counterparties in the same window — making them Blueprint §6 contaminated
  control units. `DEMO_MERCHANT_IDS = ("acc_demo", "acc_demo_up")`; `_wipe` now
  loops that tuple (still trigger-scoped and demo-only — D-125 unchanged in
  spirit). `seed_demo` still returns `acc_demo`'s 16-case summary.
- **Alternatives:** leave the demo cohort-less (rejected — the acceptance
  criteria and Module 13's SUTVA beat need a live number); a new cohort-assignment
  helper (rejected — `assign_cohort` is the sanctioned one); mutate historical
  cohort assignments (rejected — forbidden, and unnecessary: the seed builds
  fresh rows).
- **Consequence:** the demo dashboard shows treatment 5/13 ≈ 38.5%, control
  1/3 ≈ 33.3%, headline lift ≈ +5.1% (CI spans 0 — honest at this `n`), SUTVA
  2 contaminated → adjusted control 0/1, adjusted lift ≈ +38.5%. `acc_demo`'s
  descriptive metrics (`recovery_summary` etc.) are byte-identical to before.
- **Status:** IN FORCE

## D-136 — Module 12 build-roadmap classification rule and priority ordering
- **Milestone:** Module 12 — Build Roadmap
- **Decision:** The blueprint's original Module 12 (Phase 1–5, "Foundation →
  core loop → widen to 4 legs → compliance hardening → reporting/demo polish")
  describes a build order that has already happened and does not distinguish
  the two things remaining work now needs sorted by: *does a judge need this
  live*, vs. *does production need this eventually*. How should the actual
  remaining work (every open `DEFERRED.md` item + the two U-08-blocked items)
  be classified and ordered?
- **Chosen:** Four categories — **A. Demo-critical**, **B. Demo-enhancing**,
  **C. Production-hardening**, **D. Future/optional** — applying one test to
  every item: *"does this materially strengthen one of the five locked
  differentiators (root-cause diagnosis / one ledger / incrementality /
  compliance-by-construction / resource-aware prioritization) as something a
  judge can watch happen, not just read about?"* Full classification with
  per-item current state, dependency, priority, complexity, and
  data-model/state-machine/external-service flags lives in `DEFERRED.md`
  ("Build Roadmap Priority Classification"), not duplicated here.
- **Alternatives:** re-run the blueprint's original 5-phase plan verbatim
  (rejected — describes work already done, gives no signal on what's left);
  rank by blueprint section order (rejected — conflates "the blueprint mentions
  it" with "a judge needs to see it," which is exactly the trap the decision
  rule above is designed to avoid); rank by implementation complexity alone
  (rejected — cheapest-first would bury the one item that actually matters,
  A1, under a pile of low-effort production polish).
- **Key calls made under that rule** (see `DEFERRED.md` for the full table):
  wiring the ingestion→diagnosis→policy-activation→execution auto-dispatch
  chain (D-080/D-088/D-093) is ranked **A** (demo-critical, priority 1) — not
  because the demo is broken without it (the Decision-K restraint scenarios
  and the static seed already carry the differentiator-1/4 live story), but
  because a live-injected `payment_failure`/`checkout_abandonment` case
  currently dead-ends at `DETECTED` with no further autonomous action, which
  understates "one autonomous agent" for both the demo and production, and it
  is the cheapest, least risky item on the whole list (three `.apply_async`
  calls at already-tested extension points, no schema, no state-machine
  change). Live cross-leg-merge / B2B-bundle demo scenarios are ranked **B**
  (demo-enhancing) — the blueprint's Module 13 script names them as a "Live:"
  beat (differentiator 2), but the static seed already carries a real,
  explorable B2B case, so the gap is real but not blocking. Real channel
  adapters, the issuer/BIN-extraction-gated MAC lookup and `ISSUER_SPECIFIC`
  systemic detection, and every infra/security hardening item are ranked **C**
  — none is required to demonstrate a differentiator live, several need
  external accounts or an unresolved design question (U-08) resolved first.
  D-090 is **not** reopened; Temporal stays **D** (future driver swap only).
- **Consequence:** the recommended next coding milestone is a small, optional
  **"Module 12a — Close the Autonomous Loop"** (the A1 dispatch wiring + the B1
  demo scenarios) immediately before Module 13 — not a demand to build any of
  category C before judging. No code was changed to produce this
  classification; it is a documentation-only milestone.
- **Status:** IN FORCE

## D-137 — The autonomous chain is wired at the existing Celery task boundary, via an opt-in `on_case_ready` hook, never inside the pure engines
- **Milestone:** Module 12a — Close the Autonomous Loop
- **Decision:** D-080 (ingestion → diagnosis), D-088 (diagnosis → policy), and
  D-093 (policy → execution) each deliberately left the cross-module *enqueue*
  unwired, precisely because an inline/eager enqueue would run the next stage
  synchronously inside the current one and change that stage's own tested
  post-condition (e.g. Module 2's ingestion tests assert a case ends
  `DETECTED`). How do you wire real autonomy without breaking that contract or
  duplicating any engine's logic?
- **Chosen:**
  1. **Ingestion → diagnosis.** `create_or_attach_case` / `create_checkout_case`
     / `create_subscription_case` / `ingest_invoice` (and their buffer-layer
     wrappers) each gain one new, purely additive, keyword-only parameter:
     `on_case_ready: Callable[[RevenueLeakCase], None] | None = None`. It is
     called with the **canonical** case — the survivor of a §2.4 merge in
     either direction, or the bundled-into case for a B2B attach, never a
     superseded/narrower row — exactly once, only when a case was genuinely
     (re)created. Default `None` means every existing direct caller (the whole
     Module 2 test suite, the demo scenarios) is **byte-for-byte unaffected**.
     Only `torque.ingestion.tasks`'s four Celery tasks pass one, and it does no
     I/O itself — it appends the case id to a plain Python list. Only **after**
     the task's own `with session_scope()` block exits (i.e. the transaction
     has committed) does the task call `torque.ingestion.tasks.
     dispatch_diagnosis`, which enqueues `torque.diagnosis.diagnose_case_task`.
  2. **Diagnosis → policy.** No hook needed here: `diagnose_case_task` already
     receives `case_id` as its own argument. After its `with session_scope()`
     block exits, `if outcome is DiagnosisOutcome.ROUTED_TO_PLAYBOOK:` it calls
     `torque.diagnosis.tasks._dispatch_activation`, enqueuing
     `torque.policy.activate_case_task`. `ESCALATED` and `NOOP` dispatch
     nothing.
  3. **Policy → execution.** Also no hook: inside `activate_case_task`'s
     `with session_scope()` block (**same transaction**, not a further Celery
     hop), `if outcome is ActivationOutcome.RUN_CREATED:` it looks up the
     just-created `PlaybookRun` and calls the existing
     `torque.execution.scheduler.schedule_run` directly — a plain function
     call. "Scheduling execution" means arming one `ScheduledJob` row; the
     unmodified 10s/60s beat pollers (D-090) are what actually run it.
  In every case the **pure engine functions**
  (`diagnose_case`, `activate_case`, `create_or_attach_case`, …) are either
  untouched or gain only the one additive parameter — none gained a new
  responsibility, and no engine's decision logic is reproduced in the
  dispatcher.
- **Alternatives:** enqueue unconditionally inside the pure engine functions
  (rejected — this is exactly what D-080/088/093 already ruled out, and
  empirically breaks existing `celery_eager` tests that call an engine in
  isolation, e.g. `test_diagnosis_task.py`); change `BufferOutcome`/
  `DiagnosisOutcome`/`ActivationOutcome` to carry the case object (rejected —
  the outcome enums are asserted with `is` across ~15 existing test files;
  widening them to a richer return type is a much larger, riskier surface than
  one optional keyword parameter); re-derive "the case for this event" in the
  task layer by re-querying (rejected for the B2B attach path specifically — no
  event→case link exists once a `B2BInvoice` merely attaches to a
  pre-existing case; re-deriving identity there would duplicate
  `resolve_counterparty`/grouping logic the task has no business repeating).
- **Consequence:** `state_machine.py` and `guards.py` are untouched — the chain
  drives only already-legal transitions the engines already produce. No new
  Celery task, no new table. Two of the three, changed-behavior existing tests
  (`test_diagnosis_task.py::test_task_diagnoses_a_case`,
  `test_module4_task.py::test_task_creates_run`) were strengthened (bound every
  task's `_session_scope` to the harness session, seeded the catalog where
  needed) to actually prove the new chain fires, rather than silently no-op
  against an invisible second connection.
- **Status:** IN FORCE

## D-138 — `dispatch_diagnosis` always enqueues with a short countdown (closes a real, empirically-found race)
- **Milestone:** Module 12a — Close the Autonomous Loop
- **Decision:** D-137's ingestion→diagnosis dispatch has **two** real callers:
  the Celery task layer (fires strictly after its own transaction has
  committed — provably safe) and `torque.demo.scenarios.inject_scenario`
  (`dispatch=True`, called from `torque.api.demo.post_inject`), which fires
  *inside* the still-open request transaction — the same shape
  `api/webhooks.py` already uses for its own dispatches, whose `get_db`
  dependency commits only after the handler returns. Is that second shape
  actually safe?
- **Chosen:** No — confirmed **empirically**, not just in theory, against the
  real `docker compose --profile full` stack (real worker, real Redis, real
  Postgres, no test-harness monkeypatching): injecting a demo scenario and
  dispatching diagnosis with **no delay** let the worker receive and execute
  `diagnose_case_task` *before* the API request's transaction committed — the
  task saw no case at all and returned a clean, silent `NOOP`, and nothing
  ever retried it. `dispatch_diagnosis` (`torque.ingestion.tasks`) therefore
  **always** enqueues `diagnose_case_task` with a small
  `countdown` (`_DIAGNOSIS_DISPATCH_COUNTDOWN_SECONDS = 2`) — cheap, harmless
  insurance for the already-safe commit-then-dispatch callers, and the actual
  fix for the not-yet-committed one. Re-verified against the same real stack
  afterward: both the low-confidence (→ `ESCALATED_TO_HUMAN`) and
  high-confidence (→ `PLAYBOOK_ACTIVE` + a real `PlaybookRun` + a real
  `ScheduledJob`) paths now complete correctly with no manual step.
- **Alternatives:** restructure `api/deps.get_db` to expose an explicit
  post-commit hook (rejected — a much larger, shared-across-every-endpoint
  change for one caller's problem); make `diagnose_case_task` retry when it
  finds no case (rejected — would blur `NOOP`'s existing, load-bearing meaning
  "not eligible / already handled / redelivery" with a *new* meaning "try again
  shortly," everywhere `NOOP` is asserted today, not just for this caller);
  give only `torque.demo.scenarios` its own countdown, leaving the Celery-task
  callers at zero delay (rejected — one function, one safety behavior, is
  simpler to reason about and costs the safe callers nothing but two seconds of
  background latency).
- **Consequence:** `task_always_eager` (test-harness only) ignores `countdown`
  entirely and still runs inline immediately — no existing or new test's
  timing changed. A real deployment's diagnosis now starts a couple of seconds
  after a case is created rather than instantaneously; imperceptible next to
  the 30s/90s self-recovery buffers already in front of Legs 1/3.
- **Status:** IN FORCE

---

## D-139 — The AI subsystem's read-only boundary is enforced by a static import test, not a runtime guard or a Postgres role

- **Milestone:** AI Phase 0 + Phase 1 — AI Architectural Foundation &
  Read-Only Evidence Interface (`ai-layer` branch, not `main`).
- **Decision:** the new `src/torque/ai/` package must never be able to
  transition a case, execute an action, write a `CaseEvent`/`Action`, or
  otherwise mutate Torque business state — a non-negotiable requirement for
  the whole AI program, not something scoped per-phase. What is the
  *strongest practical* enforcement mechanism available now, without adding
  infrastructure Phase 0+1 doesn't otherwise need?
- **Chosen:** a static test, `tests/test_ai_boundary.py`, that parses every
  `.py` file under `src/torque/ai/` with Python's own `ast` module (no
  execution) and fails if any of them import `torque.state_machine`,
  `torque.coordination`, `torque.events`, `torque.agent_console`,
  `torque.execution`, `torque.ingestion`, `torque.policy`,
  `torque.diagnosis`, `torque.scoring`, `torque.reconciliation`,
  `torque.promises`, or `torque.api` — every one of which either mutates
  business state directly or wires up something that does. A second,
  independent, deliberately crude substring sweep in the same test file
  additionally rejects any raw `.add(` / `.delete(` / `.commit(` / SQL
  mutation keyword appearing anywhere in the package's source, as a
  belt-and-braces signal against a hypothetical future contributor who
  hand-rolls SQL to route around the import check. This is a CI-enforced
  repository fact from Phase 0 onward, not a code-review courtesy: a
  forbidden import breaks the build before merge, on every future PR to this
  package, for the life of the project.
- **Alternatives:** (1) a dedicated read-only Postgres role (`SELECT`-only
  grants) for the AI subsystem's future DB session — genuinely stronger
  defense-in-depth, but a one-time DB-admin action outside Alembic's normal
  migration flow, and there is no DB session to protect yet (Phase 0+1's
  `gather_case_evidence` takes a caller-supplied `Session`; no AI-specific
  session/connection exists until a future API layer is built). Deferred,
  **NEEDS HUMAN DECISION**, to whichever phase first stands up that session
  — recorded in `AI_BLUEPRINT.md` §11 / §20 (D-AI-17) so it is not
  forgotten, not silently dropped. (2) A runtime capability/permission
  object threaded through every AI function call — rejected as unnecessary
  complexity: there is currently exactly one AI entry point
  (`gather_case_evidence`), and it performs no write of any kind, so there
  is no runtime decision left for a capability object to gate. (3) Trusting
  code review alone — rejected outright per this program's own explicit
  requirement that the boundary be "structurally difficult," not merely
  documented.
- **Consequence:** the deterministic core is provably unreachable for
  mutation from `torque.ai` today, and any future phase that tries to add
  such a path will fail its own test suite immediately, in the same PR,
  before a maintainer even has to notice it in review. The read-only DB role
  (alternative 1) remains an open, tracked, NOT-YET-DECIDED strengthening —
  this decision does not close that question, it only defers it honestly.
- **Status:** IN FORCE (Phase 0+1); read-only DB role remains open.

---

## D-140 — The citation contract: preserve Phase 1's `reference_id` scheme unchanged; make `CaseSnapshot` citable; keep `Citation` to one field; keep `resolve_citation` pure

- **Milestone:** AI Phase 2 — Evidence Normalization + Citation Model
  (`ai-layer` branch, not `main`).
- **Decision (four bundled sub-decisions, one milestone):**
  1. **Preserve the existing `EvidenceReference.reference_id` scheme
     (`f"{source_type}:{source_id}"`) rather than adopting the illustrative
     `f"{source_type}:{case_id}:{event_seq_id or action_id}"` form.** Both
     were evaluated against the four required properties (uniqueness within
     an evidence set, stability across repeated gathering, deterministic
     derivation from an authoritative identifier, traceability back to the
     source record). The Phase 1 scheme already satisfies all four: every
     `source_id` is drawn from a genuine, already-unique authoritative
     primary key or sequence value (`CaseEvent.event_seq_id` — a single
     globally-ordered `BigInteger` sequence across every case, INV-20;
     `Action.action_id` / `PromiseToPay.promise_id` /
     `MerchantCounterparty.id` — UUID primary keys), so it is unique
     *globally*, not merely within one case's set, which is strictly
     stronger than the requirement. Embedding `case_id` again inside the id
     string would be redundant (it is already a separate field on
     `EvidenceReference`) and would only complicate parsing for zero
     uniqueness benefit. Not replaced.
  2. **`CaseSnapshot` gains a `reference: EvidenceReference` field
     (`source_type="case"`), closing a Phase 1 gap.** `SourceType` already
     reserved the `"case"` literal in Phase 1, but nothing ever constructed
     one — the case's own current-state fields (status, root cause,
     recovery score, ...) had no citation target. This is additive only (a
     new required field on a DTO nothing outside `torque.ai` constructs yet;
     no Phase-1 test broke), not a redesign of any existing field, and is
     squarely inside Phase 2's mandate to make evidence referenceable.
  3. **`Citation` carries exactly one field, `evidence_id: str`.** No
     excerpt, no confidence, no claim text — a citation names *which*
     evidence, nothing about *what claim* it supports. That belongs to
     whatever future object actually carries generated prose (Phase 4+, not
     built).
  4. **`resolve_citation(evidence: CaseEvidence, evidence_id: str) ->
     EvidenceItem | None` is pure — no `Session`, no database, no I/O.** It
     is implemented in a new, separate module, `torque.ai.citations`, that
     imports nothing beyond `torque.ai.schemas` (verified: the module has no
     `sqlalchemy`/`torque.db`/`torque.models` import at all, so it is
     *structurally* incapable of querying anything, not merely instructed
     not to). It searches only the one `CaseEvidence` object it is handed
     and returns `None` — never raises — for an unknown, fabricated,
     malformed/empty, or cross-case/cross-tenant id.
- **Alternatives considered:** a generic `EvidenceSet`/`EvidenceItem` class
  hierarchy replacing `CaseEvidence`'s named fields — rejected per the
  Phase 2 task's own instruction not to invent new evidence types or
  casually redesign the Phase 1 contract; `CaseEvidence` already *is* the
  evidence set, just not named that in code. A database-backed citation
  table or cache — rejected outright (Phase 2 explicitly forbids new
  persistence; citation identity is derived from already-authoritative
  records, never stored a second time). Raising `EvidenceNotFoundError` (or
  similar) from `resolve_citation` for a bad id, mirroring
  `gather_case_evidence`'s own not-found handling — rejected: a future
  faithfulness-evaluation layer needs to check *many* citations from one
  generated narrative and treat an unresolvable one as a data point ("this
  claim is unsupported"), not as a control-flow exception to catch per
  claim.
- **Consequence:** citation resolution is deterministic, cheap (an
  in-memory linear scan over at most a few dozen items), independently
  testable with zero database fixture cost beyond what Phase 1's
  `gather_case_evidence` already needs, and structurally cannot become a
  tenant-isolation bypass — it has no way to reach any case's evidence
  other than the one object it was given. See INV-61.
- **Status:** IN FORCE.

---

## D-141 — Retrieval architecture: Postgres FTS over an already-exact-matched candidate set; no index/migration at N≈16; terminal-state logic duplicated, not imported

- **Milestone:** AI Phase 3 — Retrieval / Precedent Engine (`ai-layer`
  branch, not `main`).
- **Decision (three bundled sub-decisions, one milestone):**
  1. **Postgres-native full-text search (`to_tsvector`/`plainto_tsquery`/
     `ts_rank`), never a vector database or embedding model, and never a
     substitute for the primary metadata filter.** `find_precedent`'s
     candidate set is first narrowed to an *exact* match on
     `(merchant_id, leg_type, root_cause_code)` plus terminal-only plus
     self/superseded exclusion — a hard filter, not a similarity score.
     Lexical relevance (`CaseEvent.reasoning` + `root_cause_label`) only
     ranks *within* that already-narrow set, as the tiebreaker before
     recency. No embeddings, no ANN index, no external search engine: the
     current corpus (dozens to low hundreds of cases) does not justify
     infrastructure built for sub-linear search over millions of rows.
  2. **No new index and no migration.** `EXPLAIN ANALYZE` was run against
     both the metadata-filter query and the lexical-ranking query on the
     seeded `acc_demo` dataset (16 cases). Both already use the existing
     `ix_revenue_leak_case_merchant_id` and `ix_case_event_case_id` indexes
     (from Milestone 1) via index scans, not sequential scans, and complete
     in well under 1ms (0.114ms and 0.849ms respectively — full plans
     recorded in `documentation/ai-memory/MILESTONES.md`'s "AI Phase 3"
     section). No new index is warranted at this scale; adding one now
     would be optimizing a query that already costs nothing measurable.
  3. **Terminal-state determination is a duplicated, cross-tested mirror of
     `torque.state_machine.TERMINAL_STATUSES`/`is_terminal` — not an
     import.** `torque.ai`'s forbidden-import boundary
     (`tests/test_ai_boundary.py`) blocks the entire `torque.state_machine`
     module, including its pure, non-mutating terminal-state logic, and
     this program's own governing instructions describe that boundary as
     "permanent." Rather than narrow the boundary test to a name-level
     allowlist (a live, considered alternative — see below), `torque.ai.
     retrieval` reimplements the exact same logic locally
     (`_terminal_statuses_for_leg`), and `tests/test_ai_retrieval.py::
     test_terminal_mirror_matches_state_machine_exactly` — a test file, not
     `src/torque/ai/*`, so free to import the real thing — exhaustively
     cross-checks the mirror against `is_terminal` for every
     `(CaseStatus, LegType)` combination. Any future drift between the two
     breaks the build loudly instead of silently.
- **Alternatives considered:** narrowing `test_ai_boundary.py`'s
  `torque.state_machine` entry from a full block to a name-level allowlist
  permitting only `TERMINAL_STATUSES`/`is_terminal` (both provably pure —
  no I/O, no mutation, no side effects) — genuinely defensible (the
  program's own instructions distinguish "state-machine *mutation*" from
  state-machine access generally), but touches a security-relevant test
  this phase's instructions call "permanent," so it was NOT taken
  unilaterally; left for the maintainer to authorize explicitly if the
  duplication-and-cross-test approach ever proves insufficient. A
  database-backed precomputed "terminal cases" view or materialized table —
  rejected (new persistence, explicitly out of scope for retrieval). Scoring
  the lexical signal with a weighted formula combining rank + recency into
  one number — rejected per the task's own explicit "no complex scoring
  formulas" instruction; a plain `(lexical_rank, opened_at)` tuple sort is
  simpler and equally correct at this scale.
- **Consequence:** retrieval has no new operational surface (no index to
  maintain, no migration to review) and stays honestly bounded to what the
  current corpus can support. The terminal-state duplication is a tracked,
  tested, documented risk (not a silent one) — the cross-check test is the
  actual safety net, not just this paragraph.
- **Status:** IN FORCE.

---

## Notes not recorded as decisions

- The **Git-history incident of 2026-09-02** (a bad commit briefly on `main`,
  then restored by the maintainer) is an operational event, not a design
  decision. It left no trace in the restored tree. Do not treat it as precedent
  for anything.
- Exact **pytest-collected test counts at the completion of M1–M5** could not be
  re-verified in this session (see `MILESTONES.md`); they are recorded there with
  an explicit "unverified" flag.
