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

---

## Invariants that are PLANNED (not yet enforced anywhere)

- Quiet-hours / `allowed_hours` enforcement on outreach (Module 5/6).
- Outreach Coordinator: 4h cross-leg quiet period, merge, defer, open-conversation
  suspension (Module 6).
- Pre-debit ≥24h gap actually blocking a retry (predicate exists; enforcement is
  Module 5/6).
- Card/UPI/NACH budget checks actually blocking a `RETRY_PAYMENT` (predicates
  exist; enforcement is Module 5).
- `SystemicEvent` → `SYSTEMIC_HOLD` case suppression: **`NETWORK_WIDE` tier
  IMPLEMENTED in M7c** (INV-27/28/29). `ISSUER_SPECIFIC` still planned (blocked
  on issuer extraction — U-08). Driving `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` (edge
  legal since M7c) + mid-run recovery is Module 5.
- `PlaybookRun.status` transition legality (Module 4/5).
- `recovery_type` derivation rules (Module 7).
