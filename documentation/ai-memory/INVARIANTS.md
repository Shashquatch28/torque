# INVARIANTS CATALOGUE

Every structurally-enforced rule in the codebase at Milestone 6b. "Structurally
enforced" = a trigger, a CHECK/UNIQUE constraint, or a `before_flush` guard —
**not** a convention or a docstring.

Enforcement layers:
- `DB-TRIGGER` — a Postgres `BEFORE ...` trigger raising an exception.
- `DB-CONSTRAINT` — a CHECK / UNIQUE / FK constraint.
- `ORM-GUARD` — `src/torque/models/guards.py` `_before_flush`, wired onto
  `SessionLocal` in `db/session.py` (`register_guards`).
- `ORM-FACADE` — `TenantScope` (`db/scoped.py`).
- `HELPER` — a sanctioned function that is the only correct write path
  (`state_machine.transition_case`, `promises.transition_promise`,
  `events.write_action_and_event`, `apply_network_directive`).

Format: **ID · Domain · Invariant · Enforcement · Mechanism · Tests · On
violation**.

---

## INV-01 — Tenant isolation
- **Domain:** all `TenantScoped` tables.
- **Invariant:** a row for merchant A is never read or written through a scope
  bound to merchant B; tenant rows always carry a non-null `merchant_id`.
- **Enforcement:** `ORM-FACADE` (primary) + `ORM-GUARD` (`_guard_case` for
  `RevenueLeakCase` network/ownership paths) + `DB-CONSTRAINT` (`merchant_id`
  `NOT NULL` + FK to `merchant`).
- **Mechanism:** `TenantScope.select()` injects `WHERE merchant_id = :m`;
  `.get()` returns `None` cross-tenant; `.add()` stamps or raises
  `CrossTenantWriteError`; `.select()` on a global model raises
  `NonTenantModelError`.
- **Tests:** `tests/test_tenancy.py`.
- **On violation:** `CrossTenantWriteError` / `NonTenantModelError` /
  `TenantScopeError`; or silent `None` on a cross-tenant `.get()`.

## INV-02 — `CaseEvent` is append-only
- **Domain:** `case_event`.
- **Invariant:** no `CaseEvent` row is ever UPDATEd or DELETEd.
- **Enforcement:** `DB-TRIGGER` + `ORM-GUARD`.
- **Mechanism:** trigger `case_event_no_mutate` (fn `torque_case_event_immutable`,
  migration `0005`) raises on UPDATE/DELETE; `_before_flush` raises
  `AppendOnlyViolation` for any dirty/deleted `CaseEvent` instance.
- **Tests:** `tests/test_case_event.py`.
- **On violation:** `AppendOnlyViolation` (ORM) or a raised SQL exception (DB).

## INV-03 — `Playbook` versions are immutable
- **Domain:** `playbook`.
- **Invariant:** a `(playbook_id, version)` row is never UPDATEd or DELETEd; an
  edit inserts `version + 1`. No `updated_at`.
- **Enforcement:** `DB-TRIGGER` + `ORM-GUARD`.
- **Mechanism:** trigger `playbook_no_mutate` (fn `torque_playbook_immutable`,
  migration `0009`); `_before_flush` raises `AppendOnlyViolation` for dirty/
  deleted `Playbook` instances.
- **Tests:** `tests/test_playbook_model.py`, `tests/test_playbook_guard.py`.
- **On violation:** `AppendOnlyViolation` / SQL exception.

## INV-04 — `RevenueLeakCase.context` is always typed
- **Domain:** `revenue_leak_case.context` (JSONB).
- **Invariant:** on every flush, `context` validates against the Pydantic model
  for its `leg_type` (`extra="forbid"`); `B2B_RECEIVABLE` must be `{}`. The
  normalized dict is written back.
- **Enforcement:** `ORM-GUARD` (`_guard_case` → `contexts.registry.validate_context`).
- **Tests:** `tests/test_context_validation.py`.
- **On violation:** `ContextValidationError`.

## INV-05 — `network_directive_tier` only ratchets toward more restrictive
- **Domain:** `revenue_leak_case.network_directive_tier`.
- **Invariant:** the tier never moves to a less restrictive value
  (`TIER_1_HARD_STOP > TIER_3_INSTRUMENT_DEAD > TIER_2_CAPPED_RETRY >
  TIMED_RETRY > NULL`); it is only written via `apply_network_directive`.
- **Enforcement:** `HELPER` + `ORM-GUARD`.
- **Mechanism:** `state_machine.apply_network_directive` checks rank then writes
  inside `network_directive_writer(session)`; `_guard_case` raises
  `OwnershipViolation` for a write outside that context and `MonotonicityViolation`
  for a downgrade.
- **Tests:** `tests/test_network_directive.py`.
- **On violation:** `OwnershipViolation` / `MonotonicityViolation`.

## INV-06 — `recovery_type` / `recovered_amount` are Module-7-only
- **Domain:** `revenue_leak_case.recovery_type`, `.recovered_amount`.
- **Invariant:** writable only inside `guards.module7_writer(session)`.
- **Enforcement:** `ORM-GUARD` (`_guard_case`).
- **Tests:** `tests/test_module7_ownership.py`.
- **On violation:** `OwnershipViolation`.

## INV-07 — `RevenueLeakCase.status` follows the locked state machine
- **Domain:** `revenue_leak_case.status`.
- **Invariant:** transitions are restricted to the §4 diagram + Part C item 1 +
  R4 (`PARTIALLY_RECOVERED → PLAYBOOK_ACTIVE` only for `B2B_RECEIVABLE`).
- **Enforcement:** `HELPER` (`state_machine.transition_case` / `assert_transition`).
- **Note:** *not* a `before_flush` guard — a raw `case.status = ...` write is not
  intercepted. Callers must use `transition_case`, which also writes the
  `STATUS_CHANGED` `CaseEvent` atomically.
- **Tests:** `tests/test_state_machine.py`.
- **On violation:** `IllegalTransitionError` (only if `transition_case` is used).

## INV-08 — Cohort assignment is once-only
- **Domain:** `merchant_counterparty.in_control_cohort`.
- **Invariant:** set exactly once; re-assignment is rejected.
- **Enforcement:** `HELPER` (`MerchantCounterparty.assign_cohort`).
- **Tests:** `tests/test_tenancy.py` / identity tests.
- **On violation:** `CohortAlreadyAssignedError`.

## INV-09 — Playbook `steps_graph` / `stopping_rules` valid + normalized on insert
- **Domain:** `playbook.steps_graph`, `.stopping_rules`.
- **Invariant:** on insert, both parse against `torque.playbooks` models and pass
  structural rules: entry names a node; edge endpoints exist; node ids unique;
  every non-terminal node has exactly one `on_success` + ≥1 fallback edge; no
  cycles; `stopping_rules` is a full `StoppingRules`. The normalized JSON is
  written back.
- **Enforcement:** `ORM-GUARD` (`_guard_playbook` → `validate_playbook`).
- **Tests:** `tests/test_playbook_graph.py`, `tests/test_playbook_validation.py`,
  `tests/test_playbook_guard.py`.
- **On violation:** `PlaybookValidationError`.

## INV-10 — `MerchantPlaybookConfig` override valid against the latest version
- **Domain:** `merchant_playbook_config.stopping_rules_override`.
- **Invariant:** the override parses as `PartialStoppingRules`;
  `deep_merge(latest_playbook.stopping_rules, override)` is a valid
  `StoppingRules`; the merged result satisfies the UPI AutoPay `max_attempts <=
  3` ceiling keyed off the latest version's `mandate_type`. Normalized override
  written back. If the playbook has no published version →
  `PlaybookNotFoundError`.
- **Enforcement:** `ORM-GUARD` (`_guard_merchant_playbook_config`).
- **Tests:** `tests/test_merchant_playbook_config.py`, `tests/test_playbook_resolution.py`.
- **On violation:** `PlaybookValidationError` / `PlaybookNotFoundError`.

## INV-11 — UPI AutoPay `max_attempts <= 3` at playbook save time
- **Domain:** `playbook.stopping_rules.max_attempts` /
  `merchant_playbook_config` merged result, when `mandate_type == UPI_AUTOPAY`.
- **Invariant:** save-time rejection if `> UPI_AUTOPAY_HARD_CAP` (3). Shared
  constant imported from `compliance.retry_rails` — defense-in-depth vs INV-16.
- **Enforcement:** `ORM-GUARD` (via `validate_playbook` / `_check_upi_ceiling`).
- **Tests:** `tests/test_playbook_validation.py`.
- **On violation:** `PlaybookValidationError`.

## INV-12 — Every `Action` has a complete `ActionCase` attribution set
- **Domain:** `action` / `action_case`.
- **Invariant:** ≥1 `ActionCase` row per `action_id`; exactly one `is_primary`;
  that row's `case_id == Action.primary_case_id`; Σ `credit_weight` ==
  `Decimal("1.00000")` exactly; the full set is present in the same flush that
  creates the `Action`. Also re-validated when `ActionCase` rows are edited on an
  already-persisted `Action` (Module 7 re-weighting).
- **Enforcement:** `ORM-GUARD` (`_guard_action_write` / `_validate_action_case_set`)
  + `DB-CONSTRAINT` (`credit_weight` unit-range CHECK; composite PK).
- **Tests:** `tests/test_action_case.py`, `tests/test_action.py`.
- **On violation:** `ActionCaseInvariantError`.

## INV-13 — `Action` and its `CaseEvent` are written in one transaction
- **Domain:** `action` ↔ `case_event`.
- **Invariant:** a new `Action` must be accompanied, in the same flush, by a new
  `CaseEvent` for `Action.primary_case_id` whose `event_type` matches the outcome
  (`ACTION_BLOCKED` iff `outcome == BLOCKED_BY_GUARDRAIL`, else `ACTION_EXECUTED`)
  and whose `payload["action_id"] == str(action.action_id)`.
- **Enforcement:** `ORM-GUARD` (`_guard_action_write`); sanctioned path is
  `events.write_action_and_event`.
- **Mechanism:** correlation is a **payload string only** — `case_event` has no
  `action_id` column and no FK.
- **Tests:** `tests/test_action_atomicity.py`.
- **On violation:** `ActionAtomicityError`.

## INV-14 — `PromiseToPay` lifecycle
- **Domain:** `promise_to_pay.status`.
- **Invariant:** a new row resolves to `PENDING` (a pre-flush `status is None`
  counts as `PENDING`); any status change on an existing row is
  `PENDING → KEPT` or `PENDING → BROKEN`; `KEPT` / `BROKEN` are terminal. No
  `CaseEvent` is written.
- **Enforcement:** `ORM-GUARD` (`_guard_promise_to_pay`) + `HELPER`
  (`promises.transition_promise` / `assert_promise_transition`).
- **Tests:** `tests/test_promise_to_pay.py`.
- **On violation:** `PromiseTransitionError`.

## INV-15 — `PromiseToPay` is at most one per `Action`
- **Domain:** `promise_to_pay.captured_via`.
- **Invariant:** unique.
- **Enforcement:** `DB-CONSTRAINT` (`UNIQUE(captured_via)` — `uq_promise_to_pay_captured_via`).
- **Tests:** `tests/test_promise_to_pay.py`, `tests/test_schema_introspection.py`.
- **On violation:** `IntegrityError`.

## INV-16 — `UPIRetryBudget.hard_cap` is locked at 3
- **Domain:** `upi_retry_budget.hard_cap`.
- **Invariant:** `hard_cap = 3` always (NPCI, not merchant-configurable).
- **Enforcement:** `DB-CONSTRAINT` (`CHECK (hard_cap = 3)` — `upi_hard_cap_locked`)
  + `server_default text("3")`.
- **Tests:** `tests/test_upi_retry_budget.py`.
- **On violation:** `IntegrityError`.

## INV-17 — Coherence CHECK constraints (illegal states unrepresentable)
- **Domain / mechanism (all `DB-CONSTRAINT`):**
  - `card_retry_budget.hard_stop_reason_coherent` —
    `hard_stop` ⇔ `hard_stop_reason IS NOT NULL`.
  - `action.outcome_block_reason_coherent` —
    `(outcome = 'BLOCKED_BY_GUARDRAIL') = (block_reason IS NOT NULL)`.
  - `action.executed_at_matches_outcome` —
    `(outcome = 'BLOCKED_BY_GUARDRAIL') = (executed_at IS NULL)`.
  - `action.cost_non_negative` — `cost IS NULL OR cost >= 0`.
  - `payment_link.paid_status_matches_paid_at` —
    `(status = 'paid') = (paid_at IS NOT NULL)` (biconditional).
  - `payment_link.amount_paid_non_negative` — `amount_paid >= 0`.
  - `systemic_event.issuer_specific_names_a_target` —
    `scope = 'NETWORK_WIDE' OR issuer_code IS NOT NULL OR network IS NOT NULL`.
  - `revenue_leak_case`: `diagnosis_confidence` ∈ [0,1] or NULL;
    `amount_at_risk >= 0`; `recovered_amount >= 0` or NULL.
  - `b2b_invoice`: `original_amount >= 0`; `outstanding_amount >= 0`;
    `outstanding_amount <= original_amount`; `days_overdue >= 0`.
  - `action_case.credit_weight_unit_range` — `credit_weight` ∈ [0,1].
  - `pre_debit_notification`: `covers_attempt_number >= 1`;
    `notified_amount >= 0`.
  - `nach_retry_policy.dishonour_count_non_negative` —
    `dishonour_count_this_fy >= 0`.
  - `card_retry_budget`: `attempts_used_24h >= 0`; `attempts_used_30d >= 0`.
  - `upi_retry_budget.upi_attempts_used_non_negative` — `attempts_used >= 0`.
  - `channel_rate_card.rate_per_unit_non_negative` — `rate_per_unit >= 0`.
  - `playbook.version_positive` — `version >= 1`.
- **Tests:** `tests/test_schema_introspection.py` + the per-entity test files.
- **On violation:** `IntegrityError`.

## INV-18 — Idempotency & relationship-uniqueness constraints
- **Domain / mechanism (all `DB-CONSTRAINT`, UNIQUE):**
  - `event.idempotency_key` unique (= `X-Razorpay-Event-Id`; never payload-derived).
  - `merchant_counterparty (merchant_id, counterparty_id)` unique.
  - `card_retry_budget (card_token_hash, merchant_id)` unique.
  - `upi_retry_budget (mandate_id, merchant_id)` unique.
  - `nach_retry_policy (mandate_id, merchant_id)` unique.
  - `merchant_playbook_config (merchant_id, playbook_id)` unique.
- **Tests:** `tests/test_event_idempotency.py`, `tests/test_schema_introspection.py`,
  per-entity tests.
- **On violation:** `IntegrityError`.

## INV-19 — `CaseEvent` payload matches its locked schema
- **Domain:** `case_event.payload`.
- **Invariant:** every payload validates against the Pydantic model registered
  for its `event_type`; no `event_type` may be written without a schema (an
  import-time assertion guarantees the registry covers `CaseEventType`).
- **Enforcement:** `HELPER` (`events.payloads.validate_payload`, called by
  `append_case_event`).
- **Tests:** `tests/test_case_event.py`, `tests/test_enums.py`.
- **On violation:** `PayloadValidationError` / `UnknownEventTypeError`.

## INV-20 — `CaseEvent.event_seq_id` is globally ordered
- **Domain:** `case_event.event_seq_id`.
- **Invariant:** a single BigInteger autoincrement sequence across **all** cases
  (not per-case).
- **Enforcement:** `DB-CONSTRAINT` (BigInteger identity PK).
- **Tests:** `tests/test_case_event.py`, `tests/test_schema_introspection.py`.

## INV-21 — WhatsApp gate #2 is fail-closed on exact `"APPROVED"`
- **Domain:** `compliance.whatsapp.approved_template_exists`.
- **Invariant:** the gate passes **iff** a matching
  `(merchant_id, leg_type, category)` row has
  `approval_status == WHATSAPP_APPROVED` (`"APPROVED"`, exact, case-sensitive).
  Every other value fails. `approval_status` is a free `String` (no DB
  constraint) — the invariant lives entirely in the predicate.
- **Enforcement:** `HELPER` (the predicate). No DB/ORM enforcement of the value.
- **Tests:** `tests/test_merchant_whatsapp_template.py`.
- **On violation:** n/a (read-only predicate) — a wrong implementation would
  admit non-approved templates; the tests guard against that (they assert the
  source references `WHATSAPP_APPROVED` and contains no bare `"APPROVED"` literal
  in the query, and that `"approved"`, `PENDING`, `PAUSED`, future statuses → `False`).

## INV-22 — Guard registration is idempotent and automatic
- **Domain:** `SessionLocal`.
- **Invariant:** `_before_flush` is attached exactly once to the sanctioned
  session factory; every session from `SessionLocal` (incl. the test harness's
  joined-transaction session) runs the guards.
- **Enforcement:** `db/session.py` `_install_guards()` → `register_guards()`
  (checks `event.contains` before `event.listen`).
- **Tests:** implicitly exercised by every guard test.

## INV-23 — Razorpay webhook: verify-before-parse, fail-closed, idempotent
- **Domain:** `POST /webhooks/razorpay/{merchant_id}` (`torque.api.webhooks`).
- **Invariant:** the request body is HMAC-SHA256-verified against the single
  mode-selected secret, **before** it is parsed. A missing/unset secret, missing
  `X-Razorpay-Signature`, or a mismatch → HTTP 200, **no `Event` row, no
  `CaseEvent`, no `RevenueLeakCase`, no side effect of any kind**. A verified
  request writes **at most one** `Event` row: skipped if the body is not a JSON
  object, if `X-Razorpay-Event-Id` is absent, if `{merchant_id}` is not a known
  merchant, or if an `Event` with that `idempotency_key` already exists
  (→ HTTP 200, not reprocessed). The write goes through `TenantScope` (INV-01),
  keyed to the path `merchant_id`.
- **Enforcement:** `HELPER` — the endpoint handler. `verify_razorpay_signature`
  (constant-time) does the compare; `UNIQUE(idempotency_key)` (INV-18) is the
  DB-level backstop, and a concurrent-insert `IntegrityError` is caught and
  treated as a duplicate.
- **Tests:** `tests/test_webhook_ingestion.py` (21).
- **On violation:** n/a at the data layer — a wrong implementation would persist
  an unverified or duplicate `Event`, or a side effect on a rejected request; the
  tests guard against each.

## INV-24 — Self-recovery buffer: a self-recovered `payment.failed` yields no case
- **Domain:** `torque.ingestion.buffer.resolve_buffered_event`.
- **Invariant:** if a `payment.captured` `Event` for the same merchant and the
  same `payment_id` or `order_id`, with `received_at >= failure.received_at`,
  exists when the buffer resolves, then the originating `payment.failed` `Event`
  ends `processed = True` and **no `RevenueLeakCase` is created**. Resolution is
  idempotent under Celery redelivery (a second run is a `NOOP`; a pre-existing
  case for the `Event` is also a `NOOP`).
- **Enforcement:** `HELPER` — the buffer function; idempotency also backed by
  the `source_event_id` check in `cases.create_or_attach_case`.
- **Tests:** `tests/test_ingestion_buffer.py`.
- **On violation:** n/a at the data layer — a wrong implementation would create a
  case for a self-recovered failure or double-create on redelivery; the tests
  guard against both.

## INV-25 — Cross-leg Merge is one-directional, lossless, idempotent
- **Domain:** `torque.ingestion.cases` / `torque.ingestion.dedup`;
  `revenue_leak_case.superseded_by_case_id`.
- **Invariant:** when an open, non-terminal `CHECKOUT_ABANDONMENT` case matches
  `(merchant_id, counterparty_id, context.cart_id == order_id)` within
  `PolicyConfig.cross_leg_dedup_window_hours`: a new `PAYMENT_DEGRADATION` case
  is created, the abandonment case's `superseded_by_case_id` points at it, the
  abandonment case's `status` is unchanged, and its context is copied into the
  survivor's `context["merged_abandonment_context"]` (no signal discarded). Only
  `CHECKOUT_ABANDONMENT` cases are ever superseded (the reverse direction is not
  implemented). Re-resolving the same `Event` is a `NOOP` — the pointer is set
  once.
- **Enforcement:** `HELPER` — `create_or_attach_case` + `find_supersedable_case`.
- **Tests:** `tests/test_cross_leg_dedup.py`.
- **On violation:** n/a at the data layer — tests assert the pointer, the
  preserved status, the carried context, window/tenant/counterparty/terminal
  exclusions, idempotency, and that the reverse direction returns nothing.

## INV-26 — Every ingestion-created case has a resolved counterparty
- **Domain:** `torque.ingestion.cases.create_or_attach_case`.
- **Invariant:** a `RevenueLeakCase` created from ingestion always has a
  non-null `counterparty_id` (matched by exact phone, then exact email, else a
  newly created `Counterparty` with safe consent defaults) and a
  `Merchant_Counterparty` row for `(merchant_id, counterparty_id)`.
- **Enforcement:** `HELPER` (`identity.resolve_counterparty`) + `DB-CONSTRAINT`
  (`revenue_leak_case.counterparty_id NOT NULL` FK).
- **Tests:** `tests/test_ingestion_counterparty.py`, `tests/test_ingestion_case_creation.py`.
- **On violation:** `IntegrityError` on flush if `counterparty_id` were null.

## INV-27 — Systemic detection is idempotent (Milestone 7c)
- **Domain:** `torque.ingestion.systemic` (`run_systemic_detection` and the §2.7
  hook `apply_active_hold_if_any`).
- **Invariant:** at most one **active** (`resolved_at IS NULL`)
  `SystemicEvent(scope=NETWORK_WIDE)` per merchant; a repeated 60-second run over
  the same data creates no second event, applies no second hold, writes no
  duplicate `SYSTEMIC_HOLD_APPLIED` / `STATUS_CHANGED`, and re-resolves nothing.
- **Enforcement:** `HELPER` — `_detect_and_hold` checks
  `_active_network_wide_event(...)` before creating; the sweep filters
  `RevenueLeakCase.systemic_event_id IS NULL` + `status == DETECTED`;
  `_check_and_resolve` filters `resolved_at IS NULL`; `transition_case` rejects
  an illegal re-transition. No advisory lock.
- **Tests:** `tests/test_systemic_detection.py`
  (`test_no_duplicate_active_event_on_repeated_run`,
  `test_repeated_run_does_not_double_hold_or_double_audit`,
  `test_repeated_resolution_run_is_idempotent`).
- **On violation:** n/a at the data layer — a wrong implementation would
  double-create / double-hold; the tests guard against it.

## INV-28 — A held case carries its `systemic_event_id` (Milestone 7c)
- **Domain:** `revenue_leak_case.systemic_event_id` / `.status`.
- **Invariant:** whenever the systemic pipeline transitions a case to
  `SYSTEMIC_HOLD` it first sets `systemic_event_id` to the event that held it;
  on resolution the case moves `SYSTEMIC_HOLD → DIAGNOSING` and the FK is **left
  populated** (audit linkage — never cleared).
- **Enforcement:** `HELPER` — `systemic._hold_case` (sets the FK, then
  `transition_case`), `systemic._check_and_resolve` (transitions, does not clear).
- **Tests:** `tests/test_systemic_detection.py`
  (`test_detected_case_is_swept_with_full_audit`,
  `test_resolution_after_sustained_quiet_requeues_to_diagnosing`).

## INV-29 — Resolution touches only its own event's held cases (Milestone 7c)
- **Domain:** `torque.ingestion.systemic._check_and_resolve`.
- **Invariant:** when a `SystemicEvent` resolves, only cases with
  `status == SYSTEMIC_HOLD AND systemic_event_id == that_event` are transitioned
  to `DIAGNOSING`. A `SYSTEMIC_HOLD` case with no / a different `systemic_event_id`
  is untouched.
- **Enforcement:** `HELPER` — the query is filtered on both columns.
- **Tests:** `tests/test_systemic_detection.py`
  (`test_resolution_only_touches_its_own_held_cases`).

## INV-30 — Leg-3 self-recovery: a self-recovered subscription failure yields no case (Milestone 8)
- **Domain:** `torque.ingestion.subscription.resolve_subscription_buffered_event`.
- **Invariant:** if a `subscription.charged` `Event` for the same merchant and
  the same `subscription.entity.id`, with `received_at >= failure.received_at`,
  exists when the 30 s buffer resolves, then the originating
  `subscription.charged.failed` `Event` ends `processed = True` and **no
  `RevenueLeakCase` is created**. Idempotent under Celery redelivery (a second
  run is `NOOP`; a pre-existing case for the `Event` is also `NOOP`).
- **Enforcement:** `HELPER` — the buffer function; idempotency also backed by the
  `source_event_id` check in `create_subscription_case`.
- **Tests:** `tests/test_subscription_buffer.py`.

## INV-31 — Leg-3 case seeds exactly its rail's retry entity, once (Milestone 8)
- **Domain:** `torque.ingestion.subscription._seed_rail_budget` and the three
  seeders.
- **Invariant:** a `SUBSCRIPTION_FAILURE` case seeds **exactly one** retry
  entity, determined by `mandate_type`: `UPI_AUTOPAY → UPIRetryBudget`
  (`attempts_used = 1`, `hard_cap = 3`), `NACH → NACHRetryPolicy`
  (`clearing_cycle_status = RETURNED`, `dishonour_count_this_fy = 1`),
  `CARD → CardRetryBudget` (`attempts_used_24h/30d = 1`). No cross-rail
  contamination; no row when `mandate_id` is empty (UPI/NACH) or no card ref
  (CARD). Each seeder is seed-if-absent (`UNIQUE(mandate_id, merchant_id)` /
  `UNIQUE(card_token_hash, merchant_id)`) — idempotent under redelivery. All in
  the case transaction.
- **Enforcement:** `HELPER` (the seeders) + `DB-CONSTRAINT` (the UNIQUE
  constraints; `CHECK (hard_cap = 3)`).
- **Tests:** `tests/test_subscription_budget_seeding.py`.

## INV-32 — Cross-leg Merge is symmetric and lossless in both directions (Module 2)
- **Domain:** `torque.ingestion.cases.create_or_attach_case` (forward) /
  `torque.ingestion.checkout.create_checkout_case` (reverse) /
  `torque.ingestion.dedup`.
- **Invariant:** whichever of a correlated `payment.failed` / `checkout.abandoned`
  pair is processed second, the **`CHECKOUT_ABANDONMENT` case is always the one
  superseded** (`superseded_by_case_id` → the `PAYMENT_DEGRADATION` case), the
  `PAYMENT_DEGRADATION` case is always canonical (`superseded_by_case_id IS
  NULL`) and carries the abandonment context in
  `context["merged_abandonment_context"]`, and the superseded case's `status` is
  **unchanged**. Correlation = same `(merchant_id, counterparty_id)` and
  abandonment `cart_id` == the payment's `order_id`, within
  `PolicyConfig.cross_leg_dedup_window_hours`. No new `CaseEventType` (Option A —
  the merge is reconstructable from the FK + merged context + each case's
  `source_event` / `STATUS_CHANGED` history). Idempotent under redelivery.
- **Enforcement:** `HELPER` — the two finders (`find_supersedable_case`,
  `find_supersedable_payment_case`) both filter `superseded_by_case_id IS NULL` +
  non-terminal; the merge writers set the FK once.
- **Tests:** `tests/test_cross_leg_dedup.py` (forward),
  `tests/test_cross_leg_dedup_reverse.py` (reverse + symmetry),
  `tests/test_module2_integrity.py`.

## INV-33 — B2B invoices bundle into one open case per (merchant, counterparty) (Module 2)
- **Domain:** `torque.ingestion.b2b.ingest_invoice`; `b2b_invoice.case_id`.
- **Invariant:** on `invoice.overdue`, if an open (non-terminal, non-superseded)
  `B2B_RECEIVABLE` case exists for `(merchant_id, counterparty_id)` the new
  `B2BInvoice` attaches to it and **no new case is created**; otherwise a new
  `B2B_RECEIVABLE` case is created (`context = {}`) and the invoice is its first
  row. There is **no time window** — a case keeps accepting invoices until it is
  terminal. `case.amount_at_risk == Σ B2BInvoice.outstanding_amount` for that
  case. Idempotent under redelivery (`event.processed` + `source_event_id`).
- **Enforcement:** `HELPER` (`ingest_invoice`) + `DB-CONSTRAINT`
  (`b2b_invoice` amount CHECKs; `event.idempotency_key` UNIQUE).
- **Tests:** `tests/test_b2b_ingestion.py`, `tests/test_module2_integrity.py`.

## INV-34 — Every ingestion entry point verifies before it parses or persists (Module 2)
- **Domain:** `POST /webhooks/razorpay/{merchant_id}` (INV-23) **and**
  `POST /internal/checkout-abandoned/{merchant_id}`.
- **Invariant:** the synthetic `checkout.abandoned` injection endpoint applies
  the identical contract to INV-23 with a **dedicated** secret
  (`Settings.checkout_injection_secret`) and `X-Torque-*` headers: HMAC-verify
  the raw body before parsing; missing/unset secret, missing/blank signature,
  mismatch, non-object body, missing `X-Torque-Event-Id`, unknown merchant, or a
  duplicate id → empty HTTP 200 with **no `Event`, no side effect**; otherwise
  exactly one `Event` via `TenantScope`. The idempotency key is header-sourced,
  never payload-derived (§2.5).
- **Enforcement:** `HELPER` — the endpoint handler; `verify_razorpay_signature`
  (constant-time) + `UNIQUE(idempotency_key)` (INV-18).
- **Tests:** `tests/test_checkout_injection.py`.

## INV-35 — A case is diagnosed at most once; diagnosis is idempotent (Module 3)
- **Domain:** `torque.diagnosis.diagnose_case`.
- **Invariant:** only a `DETECTED` case, or a `DIAGNOSING` case that has no
  `root_cause_code` yet (the §2.5 systemic-resume entry state), that is **not**
  superseded (`superseded_by_case_id IS NULL`) is diagnosable. Every other case —
  already-diagnosed, terminal, `SYSTEMIC_HOLD`, superseded, or missing — is a
  `NOOP` with no writes. Repeated task execution / redelivery therefore never
  produces a second diagnosis or a duplicate `DIAGNOSIS_COMPLETED` event.
- **Enforcement:** `HELPER` — the `_is_eligible` gate in `engine.py`.
- **Tests:** `tests/test_diagnosis_idempotency.py`.

## INV-36 — Diagnosis is atomic (Module 3)
- **Domain:** `torque.diagnosis.diagnose_case`.
- **Invariant:** the status transition(s) (`DETECTED → DIAGNOSING → {PLAYBOOK_ACTIVE
  | ESCALATED_TO_HUMAN}`), the case-field writes (`root_cause_code`,
  `root_cause_label`, `diagnosis_confidence`, `suggested_timing_adjustment`,
  `context.is_hard_decline`), and the `DIAGNOSIS_COMPLETED` `CaseEvent` all commit
  together or not at all. A failure at any point leaves the case exactly as it was
  (`DETECTED`, no root cause, no event).
- **Enforcement:** `HELPER` — the single `atomic(session)` block in `engine.py`;
  the caller's `session_scope()` for the outer transaction.
- **Tests:** `tests/test_diagnosis_atomicity.py`.

## INV-37 — Diagnosis reads only the case's own merchant's evidence (Module 3)
- **Domain:** every supporting lookup in `engine.py`.
- **Invariant:** the rail budgets (`UPIRetryBudget`, `NACHRetryPolicy`), the
  counterparty relationship (`MerchantCounterparty`), the invoices (`B2BInvoice`),
  and the source `Event` are all read through `TenantScope(session,
  case.merchant_id)`. A merchant-A case is never diagnosed with merchant-B
  evidence, even when a mandate id / counterparty is shared across merchants.
- **Enforcement:** `HELPER` — `TenantScope.select` / `.get` inject the
  `merchant_id` filter (INV-01 family).
- **Tests:** `tests/test_diagnosis_tenancy.py`.

## INV-38 — Confidence routing follows the policy threshold `T` (Module 3)
- **Domain:** `torque.diagnosis.diagnose_case`.
- **Invariant:** a diagnosed case routes `DIAGNOSING → ESCALATED_TO_HUMAN` iff
  `diagnosis_confidence < T` and `→ PLAYBOOK_ACTIVE` otherwise, where `T =
  PolicyConfig.diagnosis_confidence_threshold` (a policy value, Decision E; launch
  default 0.65). `T` is read at diagnosis time, never hardcoded at the call site.
- **Enforcement:** `HELPER` — `_apply_result` reads `_diagnosis_confidence_threshold()`.
- **Tests:** `tests/test_diagnosis_routing.py`.

## INV-39 — A run pins its playbook version at creation and never re-resolves it (Module 4)
- **Domain:** `torque.policy.activate_case` + `resolve_effective_stopping_rules`.
- **Invariant:** `activate_case` writes `(playbook_id, playbook_version)` = the
  latest catalog version at creation time; a later `version + 1` never alters an
  existing run (composite FK, D-024). Effective stopping rules resolve the merchant
  override onto the run's **pinned** version's base, so a run's graph *and* rules
  stay coherent across a mid-flight publish (D-089).
- **Enforcement:** `SCHEMA` (composite FK, INV of M4 definition) + `HELPER`
  (`_latest_version` reads MAX at creation; `resolve_effective_stopping_rules`
  loads the pinned row).
- **Tests:** `tests/test_module4_versioning.py`.

## INV-40 — At most one live PlaybookRun per case; activation is idempotent (Module 4)
- **Domain:** `torque.policy.activate_case`.
- **Invariant:** activation is a no-op when the case already has a `RUNNING` or
  `PAUSED` run — no duplicate live run is ever created for a case. A terminal run
  does not block a fresh activation (a case may have several runs over its life).
  Repeated task execution / redelivery is therefore safe.
- **Enforcement:** `HELPER` — the `_live_run` gate (no DB UNIQUE constraint, by
  design — D-089).
- **Tests:** `tests/test_module4_activation.py`, `tests/test_module4_task.py`.

## INV-41 — A PLAYBOOK_ACTIVE case is never left without a run or an escalation (Module 4)
- **Domain:** `torque.policy.activate_case`.
- **Invariant:** for an eligible `PLAYBOOK_ACTIVE` case, activation always reaches
  a terminal disposition — either a `PlaybookRun` (RUN_CREATED) or
  `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN` via the existing legal edge when no
  catalog playbook applies or the merchant disabled it (D-086). The case is never
  parked in `PLAYBOOK_ACTIVE` with no run, and no new state/edge is invented. The
  escalation is a normal `STATUS_CHANGED` (no run-created event type — D-089).
- **Enforcement:** `HELPER` — `activate_case` branches; `transition_case` enforces
  the legal edge.
- **Tests:** `tests/test_module4_activation.py`.

## INV-42 — Every catalog playbook is valid and reachable (Module 4)
- **Domain:** `torque.policy.catalog`.
- **Invariant:** every one of the eleven catalog `steps_graph`/`stopping_rules`
  clears the same save-time validation as any playbook (ORM-seeded, D-085), and
  every catalog playbook is the selection target of at least one legal
  `(leg, root_cause[, mandate])` — nothing in the catalog is dead, nothing
  malformed can seed.
- **Enforcement:** `ORM-GUARD` (`before_flush` validates each graph at seed) +
  `HELPER` (selection map).
- **Tests:** `tests/test_module4_catalog.py`, `tests/test_module4_selection.py`.

## INV-43 — At most one pending timer per run; step execution is exactly-once (Module 5)
- **Domain:** `scheduled_job`, `torque.execution.scheduler` / `runner`.
- **Invariant:** a `PlaybookRun` has at most one pending `scheduled_job`
  (`UNIQUE(run_id)`). The poller claims due rows `FOR UPDATE SKIP LOCKED`, so two
  workers never process the same job; each execution tick (action + budget +
  `active_step_id` + `CaseEvent`s + the job row) is all-or-nothing — it runs inside
  its own `begin_nested()` SAVEPOINT within the poll pass (D-095), so it commits or
  rolls back as one unit AND one job's failure (`StepResult.ERROR`) cannot roll back
  a sibling's committed work or stall the stratum. A crash rolls the tick back
  leaving the timer for the next poll (at-least-once delivery, exactly-once effect)
  — no double action, no double attempt consumption, no double advancement.
- **Enforcement:** `DB` (`UNIQUE(run_id)` + `SKIP LOCKED`) + `HELPER` (per-job
  SAVEPOINT in `execute_due_jobs` around the atomic `execute_due_job`).
- **Tests:** `tests/test_module5_idempotency.py` (incl. two-connection concurrency),
  `tests/test_module5_scheduler.py`, `tests/test_module5_corrections.py` (poison-pill
  isolation + per-job atomicity).

## INV-44 — A run executes only on its pinned playbook version (Module 5)
- **Domain:** `torque.execution.runner`.
- **Invariant:** runtime traversal reads the graph + base rules of the run's pinned
  `(playbook_id, playbook_version)` — never `MAX(version)`. Publishing a newer
  version never alters an in-flight run's graph, `active_step_id` space, or
  effective stopping rules (which merge the merchant override onto the pinned base).
- **Enforcement:** `HELPER` (`runner` / `resolve_effective_stopping_rules` load by
  the composite key) atop the composite FK (D-024).
- **Tests:** `tests/test_module5_execution.py::test_execution_uses_pinned_version_not_latest`.

## INV-45 — Execution reads only the run's own merchant's data (Module 5)
- **Domain:** every lookup in `torque.execution.runner` / `guardrails` / `scheduler`.
- **Invariant:** the run, case, source Event, rail budgets (Card/UPI/NACH), systemic
  event, and the timer are all reached through `TenantScope(job.merchant_id)` — a
  merchant-A run never reads or consumes merchant-B data even when a card token /
  mandate id is shared across tenants. The poller is cross-merchant but processes
  each job in its own merchant scope.
- **Enforcement:** `HELPER` (`TenantScope` on every lookup).
- **Tests:** `tests/test_module5_tenancy.py`.

## INV-46 — The UPI AutoPay hard cap is never exceeded (Module 5)
- **Domain:** `torque.execution.guardrails` + `runner` retry-budget consumption.
- **Invariant:** a UPI AutoPay `RETRY_PAYMENT` fires only while
  `attempts_used < 3 AND mandate_cancelled_at IS NULL` (§3 gate); a firing retry
  increments `attempts_used` by exactly one in the same transaction, under a row
  lock (`FOR UPDATE`), so concurrent ticks cannot double-count and a forbidden
  attempt cannot execute. Module 5 never fabricates `mandate_cancelled_at` (NPCI /
  Module 2 owns it) or NACH return data (bank return file, external).
- **Enforcement:** `HELPER` (`upi_attempt_gate_open` + row-locked increment).
- **Tests:** `tests/test_module5_guardrails.py`, `tests/test_module5_idempotency.py`.

## INV-47 — One guardrail decision path: the `GuardrailEngine` facade (Module 6)
- **Domain:** `torque.execution.runner` guardrail dispatch.
- **Invariant:** the runtime tick consults exactly one function —
  `torque.coordination.guardrail_engine.GuardrailEngine.check()` — for the
  allow / block / defer / auto-insert decision on every actionable step. The
  facade **composes** the existing pure predicates
  (`torque.execution.guardrails`, `torque.compliance.*`,
  `torque.coordination.outreach_coordinator`) and never re-implements them; the
  §5.2 sequence runs first-failure-wins (retry: hard-stop → rail budget →
  pre-debit self-heal → systemic; contact: systemic → cross-leg quiet period →
  WhatsApp gate #1/#2 → open-conversation → quiet-hours). Return shape is the
  four-way `GuardDecision` (D-097).
- **Enforcement:** `HELPER` — `runner._guardrails` calls only the facade;
  `check_retry_guardrails` / `check_contact_guardrails` remain as the composed
  predicates, not a second dispatch path.
- **Tests:** `tests/test_module6_guardrail_engine.py`,
  `tests/test_module6_whatsapp_gate.py`,
  `tests/test_module6_outreach_coordinator.py`.

## INV-48 — Escalation ceiling routes a run to a human before it exhausts (Module 6 §6.3)
- **Domain:** `torque.execution.runner._escalation_ceiling_hit` /
  `_escalate_on_ceiling`; `revenue_leak_case.status`; `playbook_run.status`.
- **Invariant:** once a run's unsuccessful-attempt count
  (`BLOCKED_BY_GUARDRAIL` + `FAILED` + `NO_RESPONSE` Actions) reaches
  `stopping_rules.escalation_ceiling`, the next tick — **before** the
  execution-layer stopping bounds and before any further action — transitions the
  case `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN` (existing legal edge, trigger
  `"escalation_ceiling"`), sets the run `ESCALATED`, enqueues the case
  (`ESCALATION_CEILING`), deletes the timer, and returns
  `StepResult.ESCALATED_CEILING`. Exactly one transition — a graph-terminal
  `ESCALATE_HUMAN` node never also runs.
- **Enforcement:** `HELPER` (the tick check) + `HELPER`
  (`state_machine.transition_case` for the edge legality).
- **Tests:** `tests/test_module6_escalation_ceiling.py`.

## INV-49 — Human queue is idempotent per case and tenant-scoped (Module 6 §6.4)
- **Domain:** `human_queue`; `torque.coordination.human_queue`.
- **Invariant:** at most one `HumanQueueEntry` per `case_id`
  (`UNIQUE(case_id)`); `enqueue()` returns the existing row unchanged if the case
  is already queued (first reason wins), so any feeder — the
  `ESCALATED_TO_HUMAN` sweep, the escalation-ceiling path, a broken
  `PromiseToPay` — is safe to re-run. Every read/write is through `TenantScope`.
- **Enforcement:** `DB-CONSTRAINT` (`UNIQUE(case_id)`) + `ORM-FACADE`
  (`TenantScope`) + `HELPER` (`enqueue` checks first).
- **Tests:** `tests/test_module6_human_queue.py`.

## INV-50 — A merged outreach Action conserves attribution exactly (Module 6 Part A §5)
- **Domain:** `torque.coordination.merge.execute_merged`; `action` / `action_case`.
- **Invariant:** a merge writes **one** `Action` (attributed to the
  higher-`priority` run) with **one `ActionCase` per participating case**;
  `credit_weight` is proportional to each case's `amount_at_risk` with the primary
  taking the exact remainder, so Σ `credit_weight` == `Decimal("1.00000")` (the
  same guard as INV-12). Every participating run then advances on the send
  outcome (its own `STEP_TRANSITIONED` + `active_step_id` + reschedule) so none
  can re-fire; with no `multi_case_template` the primary sends single-case and
  each secondary is deferred (`OUTREACH_COORDINATOR_DEFERRED`), never dropped.
- **Enforcement:** `HELPER` (the merge weights) + `ORM-GUARD`
  (`_validate_action_case_set`, INV-12).
- **Tests:** `tests/test_module6_merge.py`.

## INV-51 — `escalation_ceiling <= max_attempts` at playbook-save time (Module 6 §6.3)
- **Domain:** `playbook.stopping_rules` / `merchant_playbook_config` merged result.
- **Invariant:** save-time rejection if `escalation_ceiling > max_attempts` — the
  ceiling is a sub-bound on unsuccessful attempts and cannot exceed the attempt
  cap. Checked on the base rules **and** on any merchant override merged onto them
  (the same defense-in-depth path as INV-11, the UPI cap).
- **Enforcement:** `ORM-GUARD` (via `validate_playbook` /
  `validate_merchant_playbook_config` → `_check_escalation_ceiling`).
- **Tests:** `tests/test_module6_validation.py`.

## INV-52 — Reconciliation of one `Event` is atomic and idempotent (Module 7)
- **Domain:** `torque.reconciliation.reconcile.reconcile_event`.
- **Invariant:** the whole reconciliation of one success `Event` — the case
  status transition(s), the `recovery_type` / `recovered_amount` / `closed_at`
  writes, any `B2BInvoice.outstanding_amount` decrement, any
  `ActionCase.credit_weight` re-split, the `PAYMENT_RECONCILED` `CaseEvent`, the
  human-queue removal, and `Event.processed = True` — commit together or not at
  all (the Celery task's `session_scope`). A re-run on a `processed` `Event`, a
  missing `Event`, or a non-reconciliation type is a `NOOP` with no writes
  (idempotent under Celery redelivery). A second distinct payment for an
  already-terminal case is a `NO_MATCH` (no second close, no duplicate
  `PAYMENT_RECONCILED`).
- **Enforcement:** `HELPER` — the single transactional entry point; the
  `Event.processed` / terminal-status gates.
- **Tests:** `tests/test_module7_idempotency.py`.

## INV-53 — `recovery_type` / `recovered_amount` are written only by Module 7, inside `module7_writer` (Module 7 realises INV-06)
- **Domain:** `revenue_leak_case.recovery_type`, `.recovered_amount`.
- **Invariant:** reconciliation is the sole writer; every flush that carries the
  change happens inside `guards.module7_writer(session)` (the context is held
  open across the transition + event + queue flushes, not just the assignment).
  `AGENT_ASSISTED` requires a non-blocked `Action` for the case within
  `PolicyConfig.attribution_window_hours`; a direct `PaymentLink` match is always
  `AGENT_ASSISTED`; a §7.1.4 pre-diagnosis close is always `SELF_RECOVERED`.
- **Enforcement:** `ORM-GUARD` (`_guard_case` — `OwnershipViolation` outside
  `module7_writer`) + `HELPER` (reconcile holds the context).
- **Tests:** `tests/test_module7_ownership.py`, `tests/test_module7_reconcile_*`.

## INV-54 — Recovery never double-closes a case under concurrency (Module 7)
- **Domain:** `torque.reconciliation.reconcile` case matching.
- **Invariant:** every candidate `RevenueLeakCase` row a reconciliation may close
  is read `SELECT … FOR UPDATE`, so two workers reconciling different payments
  for the same case serialise — the first closes it, the second's match then
  sees a terminal case and no-ops. Exactly one `RECOVERED` transition and one
  `PAYMENT_RECONCILED` per case per recovery.
- **Enforcement:** `DB` (`FOR UPDATE` row locks) + `HELPER` (terminal-status
  skip).
- **Tests:** `tests/test_module7_idempotency.py::test_two_workers_race_one_recovery`
  (two real connections).

## INV-55 — B2B `amount_at_risk` tracks `Σ B2BInvoice.outstanding_amount` (Module 7 maintains INV-33)
- **Domain:** `revenue_leak_case.amount_at_risk` (B2B) / `b2b_invoice.outstanding_amount`.
- **Invariant:** a partial B2B payment is applied to the case's invoices
  oldest-`due_date`-first (`FOR UPDATE`), and `case.amount_at_risk` is set to the
  new `Σ outstanding` in the same transaction; `case.recovered_amount`
  accumulates the payments. When `Σ outstanding` reaches 0 the case is
  `RECOVERED` (a two-hop through `PLAYBOOK_ACTIVE` if it was already
  `PARTIALLY_RECOVERED`, both edges legal for B2B) and `recovered_amount` equals
  the full original balance.
- **Enforcement:** `HELPER` + `DB-CONSTRAINT` (`b2b_invoice` amount CHECKs,
  `outstanding_amount <= original_amount`, `>= 0`).
- **Tests:** `tests/test_module7_case_closure.py`.

---

## INV-56 — One authoritative recovery-score formula; every consumer reads it through the `priority()` seam (Module 8)
- **Domain:** `torque.scoring.compute_recovery_score` /
  `torque.coordination.outreach_coordinator.priority`.
- **Invariant:** `(probability × amount_at_risk) ÷ cost` is computed in exactly
  one place (`compute_recovery_score`). The Outreach Coordinator merge
  primary-selection (`merge._ordered`) and the human queue
  (`human_queue.enqueue` default / `recompute_open_cases` refresh) both obtain
  the number via `outreach_coordinator.priority(session, case)`, which delegates
  to `compute_recovery_score(...).score`. No consumer re-derives probability,
  cost, or the ratio; `human_queue` / `merge` never import
  `torque.scoring.benchmarks` / `torque.scoring.cost` / `compute_recovery_score`.
- **Enforcement:** `HELPER` (single implementation + one delegating seam) +
  `TEST` (a source-inspection test in
  `tests/test_module8_integration.py::test_consumers_route_through_the_seam_not_the_formula`).
- **Tests:** `tests/test_module8_integration.py`, `tests/test_module8_score.py`.

## INV-57 — The recovery score is deterministic, bounded, and never divides by zero (Module 8)
- **Domain:** `torque.scoring` — `RecoveryScore`.
- **Invariant:** for a fixed `(case state, related rows, now)` the score and its
  full breakdown are byte-identical on every call (exact `Decimal`, no float,
  quantised 4 dp). `probability ∈ [0, 1]` (cold-start benchmark × warm-start
  multiplier clamped to `[cap_low, cap_high]`, result clamped `[0, 1]`).
  `effective_cost ≥ PolicyConfig.recovery_score_cost_floor > 0` always — a zero /
  unpriced / absent forward cost floors, so `(p × amount) ÷ cost` can never raise
  `ZeroDivisionError`. A negative `amount_at_risk` raises `RecoveryScoreError`
  (structurally impossible via the `amount_at_risk >= 0` CHECK); `None` → score 0.
  Terminal / superseded cases are never scored.
- **Enforcement:** `HELPER` (clamps + floor + quantisation in
  `benchmarks` / `cost` / `score`) + `DB-CONSTRAINT`
  (`amount_at_risk >= 0`, `rate_per_unit >= 0`).
- **Tests:** `tests/test_module8_correctness.py`, `tests/test_module8_probability.py`,
  `tests/test_module8_cost.py`.

---

## INV-58 — Reporting is read-only, tenant-scoped, and derives from authoritative data (Module 9)
- **Domain:** `torque.reporting.metrics` / `torque.api.reporting`.
- **Invariant:**
  1. **Read-only** — no Module 9 code path writes any row (no `Action`,
     `CaseEvent`, case mutation, no persisted aggregate — D-114). The reporting
     router exposes only `GET` endpoints.
  2. **Tenant-scoped** — every aggregation filters by `merchant_id`
     (via `TenantScope`, or a join to `revenue_leak_case.merchant_id` for
     `case_event`). Merchant A's summary, breakdowns, time series, exception
     report, case list, case detail, and event stream never include merchant B's
     rows; a cross-tenant `case_id` returns `None` (→ HTTP 404).
  3. **Derived, not authoritative** — `recovery_type` / `recovered_amount` come
     from Module 7 (INV-53) and are read verbatim (§9.3); `revenue_at_risk` is
     computed per D-115; there is no second definition of "recovered".
  4. **Deterministic** — repeated queries over an unchanged DB return
     byte-identical results (exact `Decimal`; no cache to drift or double-count).
- **Enforcement:** `HELPER` (all reads through `TenantScope` / an explicit
  `merchant_id` join; a GET-only `APIRouter`) + `TEST` (a schema-introspection
  test asserts the router's method set is exactly `{"GET"}`; `test_module9_
  tenant_isolation` exercises every function and endpoint cross-merchant).
- **Tests:** `tests/test_module9_tenant_isolation.py`,
  `tests/test_module9_attribution.py`, `tests/test_module9_batch.py`,
  `tests/test_schema_introspection.py`.
- **Module 10 extension:** the `top_at_risk_cases` / `human_queue_list` /
  `recent_activity` reads and the enriched `case_detail` follow the same rules
  (read-only, `TenantScope`d, `recovery_score` / `recovery_score_breakdown` read
  verbatim from Module 8). The reporting router stays GET-only.
  `tests/test_module10_tenant_isolation.py`.
- **Module 9b extension:** `torque.reporting.incrementality` +
  `GET /reports/{m}/incrementality` follow the same rules — read-only (a
  row-count + `control_group`-snapshot test proves repeated calls write
  nothing), `TenantScope`d for the caller's own cohort. The **one** cross-merchant
  read (`_contaminated_control_counterparties`, Blueprint §6 SUTVA) is bounded
  both ways: `WHERE counterparty_id IN (:the caller's own control counterparties)`
  so it can only return ids the caller already holds, and it selects only
  `counterparty_id` (reduced to a `set` before returning) — no other merchant's
  id, case ids, amounts, statuses, outcomes, or counts are read or exposed. The
  cohort inputs (`in_control_cohort` / `control_group`) are never written.
  `tests/test_module9b_api.py`, `tests/test_module9b_sutva.py`.

## INV-59 — Agent Console human overrides use only legal edges, tenant-scoped, guarded (Module 10)
- **Domain:** `torque.agent_console.resolve` / `torque.api.agent_console`.
- **Invariant:**
  1. **Legal edges only** — `resolve_escalation` transitions
     `ESCALATED_TO_HUMAN → {RECOVERED, PARTIALLY_RECOVERED, WRITTEN_OFF}` (edges
     already in `state_machine.py`); `pause_case` / `unpause_case` use
     `PLAYBOOK_ACTIVE ↔ PAUSED`. Every transition goes through `transition_case`
     (validates + writes `STATUS_CHANGED`). Module 10 adds **no** state-machine
     edge.
  2. **State-gated** — `resolve` requires `status == ESCALATED_TO_HUMAN`;
     `pause` requires `PLAYBOOK_ACTIVE`; `unpause` requires `PAUSED`. Any other
     current state raises `HumanResolutionError` (→ HTTP 409) and writes nothing.
  3. **Tenant-scoped** — the case is fetched via `TenantScope(session,
     merchant_id).get(...)`; a case owned by another merchant is
     `CaseNotFoundError` (→ HTTP 404), never mutated.
  4. **Guarded recovery write** — a `→ RECOVERED` / `→ PARTIALLY_RECOVERED`
     resolution records `recovered_amount` + `recovery_type = AGENT_ASSISTED`
     only inside `guards.human_resolution_writer`; a bare write still raises
     `OwnershipViolation`.
  5. **Audited** — every resolution writes exactly one `HUMAN_RESOLVED`
     `CaseEvent` (`actor = HUMAN`, payload `{resolution, agent_id}`) and removes
     the case from the human queue.
- **Enforcement:** `HELPER` (`transition_case` + status checks + `TenantScope` +
  `human_resolution_writer`) + `DB` (`state_machine` + the `case_event` payload
  schema) + `TEST` (`tests/test_module10_agent_console.py`,
  `tests/test_module10_api.py`).
- **Tests:** `tests/test_module10_agent_console.py`,
  `tests/test_module10_tenant_isolation.py`, `tests/test_schema_introspection.py`.

---

## INV-60 — `torque.ai` is structurally read-only: no case transition, no action execution, no CaseEvent/Action write, ever (AI Phase 0)

- **Domain:** `src/torque/ai/*` (branch `ai-layer`, not yet on `main`).
- **Invariant:**
  1. **No mutation-capable import.** `torque.ai.*` never imports
     `torque.state_machine`, `torque.coordination`, `torque.events`,
     `torque.agent_console`, `torque.execution`, `torque.ingestion`,
     `torque.policy`, `torque.diagnosis`, `torque.scoring`,
     `torque.reconciliation`, `torque.promises`, or `torque.api`.
  2. **No write-shaped call in source.** No file under `src/torque/ai/`
     contains `.add(`, `.delete(`, `.commit(`, or a raw SQL mutation
     keyword (`INSERT INTO`, `UPDATE `, `DELETE FROM`) anywhere in its text.
  3. **Reads only through `TenantScope`.** Every query in
     `torque.ai.evidence` goes through `torque.db.scoped.TenantScope` — the
     same, unmodified tenant-isolation facade every other Torque read path
     uses (INV-01) — except `CaseEvent` (not `TenantScoped` at the column
     level), which is filtered by an already-ownership-verified `case_id`,
     the same posture INV-58 documents for `torque.reporting.metrics`
     reading this same table.
  4. **DTOs only, never an ORM row, cross the package boundary.**
     `torque.ai.evidence.gather_case_evidence` returns
     `torque.ai.schemas.CaseEvidence` — a frozen, `extra="forbid"` Pydantic
     object — never a `RevenueLeakCase`/`CaseEvent`/`Action` instance.
  5. **No PII field is ever read.** `Counterparty.name` / `.phone` /
     `.email` are never queried by anything under `torque.ai` (the package
     never queries `Counterparty` at all); `Action.content_sent` is
     excluded from `torque.ai.schemas.ActionEvidence`.
- **Enforcement:** `TEST` (`tests/test_ai_boundary.py` — a static `ast`-based
  import-graph check plus an independent substring write-call sweep, both
  CI-run on every change to `src/torque/ai/`) + `HELPER`
  (`torque.db.scoped.TenantScope`, reused unmodified) + `TEST`
  (`tests/test_ai_evidence.py`'s cross-tenant and PII-exclusion cases).
  Unlike every other invariant in this document, this one has **no DB-level
  enforcement** (no CHECK constraint, no trigger) — there is no schema for
  it to constrain; the entire mechanism is the static test plus the absence
  of any write capability in the package's code. See D-139 for why a
  runtime/DB-role mechanism was considered and deferred, not adopted, at
  this phase.
- **Tests:** `tests/test_ai_boundary.py`, `tests/test_ai_evidence.py`,
  `tests/test_ai_config.py`.

---

## INV-61 — AI citation resolution is deterministic, pure, and never silently fabricates a match (AI Phase 2)

- **Domain:** `src/torque/ai/citations.py` + `torque.ai.schemas.{Citation,
  EvidenceReference}` (branch `ai-layer`, not yet on `main`).
- **Invariant:**
  1. **Evidence ids are deterministic.** `EvidenceReference.reference_id`
     is derived solely from an authoritative Torque primary key or sequence
     value (`CaseEvent.event_seq_id`, `Action.action_id`,
     `PromiseToPay.promise_id`, `MerchantCounterparty.id`, or
     `RevenueLeakCase.case_id` for the snapshot itself) — never from array
     position, a timestamp, or randomly generated data. Calling
     `torque.ai.evidence.gather_case_evidence` twice for the same,
     unchanged case produces byte-identical ids both times.
  2. **Ids are unique within (in fact, across) an evidence set.** No two
     `EvidenceItem`s returned for one case ever share a `reference_id` —
     verified globally unique in practice, since every underlying source id
     already is.
  3. **Resolution is exact-match only, and scoped to the evidence set it is
     given.** `resolve_citation(evidence, evidence_id)` returns an item only
     when `evidence_id` equals that item's own `reference_id` exactly — no
     fuzzy matching, no partial matching, no fallback heuristic. It searches
     only the one `CaseEvidence` object passed to it; an id that is valid
     for a *different* case's (or a different tenant's) evidence set never
     resolves, because no other evidence set is ever consulted.
  4. **Unresolved is `None`, never an exception.** An unknown, fabricated,
     malformed, or empty `evidence_id` returns `None`. This is deliberate:
     a future faithfulness-evaluation layer (not built yet) must be able to
     check many citations from one generated narrative and record each
     unresolved one as "unsupported claim" data, not as a per-citation
     `try`/`except`.
  5. **Resolution performs no I/O and no mutation.** `torque.ai.citations`
     imports nothing beyond `torque.ai.schemas` — no `sqlalchemy`, no
     `Session`, no `torque.db`, no `torque.models`. It cannot query the
     database because it has no code path to reach one.
- **Enforcement:** `TEST` (`tests/test_ai_citations.py` — id uniqueness,
  repeated-gathering stability, exact-match resolution, fabricated/
  malformed/cross-case/cross-tenant non-resolution, all against real,
  database-backed `CaseEvidence` objects) + `TEST`
  (`tests/test_ai_boundary.py`'s import-graph check, which also covers
  `torque.ai.citations` — proving item 5 structurally, not just by
  inspection).
- **Tests:** `tests/test_ai_citations.py`, `tests/test_ai_boundary.py`.

---

## Invariants that are PLANNED (not yet enforced anywhere)

- Pre-debit ≥24h gap actually blocking a retry: **IMPLEMENTED in Module 5**
  (auto-insert self-heal; INV-46 family) — surfaced through the Module 6 facade
  (INV-47).
- Card/UPI/NACH budget checks actually blocking a `RETRY_PAYMENT`: **IMPLEMENTED
  in Module 5** (INV-46) — surfaced through the Module 6 facade (INV-47).
- Quiet-hours / `allowed_hours` on outreach + the Outreach Coordinator (4h
  cross-leg quiet period, merge, defer, open-conversation): **IMPLEMENTED in
  Module 6** (INV-47/50).
- `SystemicEvent` → `SYSTEMIC_HOLD` case suppression: **`NETWORK_WIDE` tier
  IMPLEMENTED in M7c** (INV-27/28/29). `ISSUER_SPECIFIC` still planned (blocked
  on issuer extraction — U-08). Driving `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` (edge
  legal since M7c) + mid-run recovery is a Module 5 blueprint gap (F-4).
- `PlaybookRun.status` transition legality (still enum + assignment only).
- `recovery_type` derivation rules: **IMPLEMENTED in Module 7** (INV-52/53/54).
- The Module 8 `(probability × amount_at_risk) ÷ cost` score: **IMPLEMENTED in
  Module 8** (INV-56/57) — through the `priority()` seam (D-098 / D-113).
- Business recovery reporting: **IMPLEMENTED in Module 9** (INV-58) — read-only,
  tenant-scoped, derived on demand. Incrementality / causal measurement is still
  planned ("Module 9b" — D-121 / U-10).
