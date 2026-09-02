# ARCHITECTURE SNAPSHOT

State as of Milestone 7c (M6b commit `47cf6d7` + uncommitted M7a + M7b + M7c).
Derived documentation — verify against code before relying on any single line.

**Every item is tagged:**

- `IMPLEMENTED` — exists in code + migration + tests at HEAD.
- `PLANNED` — specified in the blueprint, not yet built; owned by a named later module.
- `DEFERRED` — deliberately excluded from the milestone that touched its area; see `DEFERRED.md`.
- `UNRESOLVED` — design not settled; see `UNRESOLVED.md`.

Do not describe `PLANNED` / `DEFERRED` behaviour as if it exists.

---

## 1. Domain boundaries / modules

| Module | Scope | Status |
|---|---|---|
| 1 — Core Data Model | shared case object, tenancy, PII/DPDP, event sourcing, retry-rail compliance entities | `IMPLEMENTED` (M1–M6b) |
| 2 — Signal Ingestion | webhook intake, signature verify, idempotency, out-of-order buffer, cross-leg dedup, systemic detection job | **PARTIAL** — `IMPLEMENTED`: webhook verify/idempotency/`Event` write (M7a); Leg-1 self-recovery buffer + cross-leg dedup (live direction) + `PAYMENT_DEGRADATION` case creation + `CardRetryBudget` seeding (M7b); **§2.5 `NETWORK_WIDE` systemic detection + hold/resume + the §2.7 ingestion hook + the `PLAYBOOK_ACTIVE→SYSTEMIC_HOLD` edge (M7c)**. Celery/Redis broker-only + Celery beat. `PLANNED`: `ISSUER_SPECIFIC` detection (U-08); Leg 2/3/4 ingestion; reverse Merge; `UPIRetryBudget` seeding (Leg 3); dispatch to Module 3 |
| 3 — Diagnosis Engine | root-cause classification + confidence; owns `root_cause_code` enum | `PLANNED` |
| 4 — Policy & Playbook Engine | root cause → bounded action graph; playbook authoring/validation (validation part `IMPLEMENTED` in M4) | `PLANNED` (runtime) |
| 5 — Execution / Orchestration | channel adapters, retry-budget enforcement, atomic Action+CaseEvent write (primitive `IMPLEMENTED` in M5), Temporal workflow | `PLANNED` (runtime) |
| 6 — Compliance & Cross-Leg Guardrail Engine | `GuardrailEngine.check()`, Outreach Coordinator, escalation ceiling, human queue | `PLANNED` |
| 7 — Reconciliation & Attribution | match payments → cases, `AGENT_ASSISTED` vs `SELF_RECOVERED`, write `credit_weight` | `PLANNED` |
| 8 — Recovery Scoring | `(probability × amount) ÷ cost`, cold-start lookup | `PLANNED` |
| 9 — Reporting & Measurement | ₹ recovered, incrementality lift + CI, exception list | `PLANNED` |
| 10 — UI/UX | merchant dashboard, agent console, demo surface | `PLANNED` |
| 11 — Tech Stack & Infra | Temporal / BullMQ / polling fallback | `PLANNED` |
| 12 — Build Roadmap | phase plan (no calendar dates — Part D item 3) | `PLANNED` / `UNRESOLVED` |
| 13 — Demo Script | judging narrative | `PLANNED` |

---

## 2. Entities (blueprint §3) — all `IMPLEMENTED`

23 tables. One ORM file each under `src/torque/models/`. All are typed
SQLAlchemy 2.0 models on the shared `Base` with `NAMING_CONVENTION`.

### 2.1 Identity & tenancy
- **`merchant`** (`Merchant`) — PK `merchant_id` (Razorpay id, `String(64)`, not
  a UUID). `channels_enabled` / `risk_appetite_config` JSONB. **Not**
  `TenantScoped` (it *is* the tenant). `IMPLEMENTED`.
- **`counterparty`** (`Counterparty`) — UUID PK. **The only raw PII in the
  system**: `name`, `phone`, `email` (all nullable for erasure). Consent:
  `whatsapp_opt_in`, `payment_failure_nudge_consent`, `language_pref`
  (`language_pref` enum), `consent_log` JSONB. `redact_pii()` nulls the three
  fields + appends an audit entry. **Global scope — no `merchant_id`** (R3).
  `IMPLEMENTED`.
- **`merchant_counterparty`** (`MerchantCounterparty`) — UUID PK,
  `UNIQUE(merchant_id, counterparty_id)`. `TenantScoped`. Carries per-merchant
  relationship data, the incrementality cohort (`in_control_cohort`,
  `cohort_assigned_at`), and `active_wa_conversation_expires_at`. `assign_cohort()`
  is once-only (raises `CohortAlreadyAssignedError`). `IMPLEMENTED`.

### 2.2 Case spine
- **`revenue_leak_case`** (`RevenueLeakCase`) — UUID PK. `TenantScoped`. The
  atomic unit. Key columns: `leg_type`, `source_event_id`→`event`,
  `counterparty_id`, `systemic_event_id` (nullable FK→`systemic_event`),
  `amount_at_risk` `Numeric(14,2)`, `status` (`case_status` enum, default
  `DETECTED`), `root_cause_code`/`root_cause_label` (**plain strings** — enum
  owned by Module 3, deliberately not frozen), `network_directive_mac_code` +
  `network_directive_tier` (**two discrete columns, not a JSON blob**),
  `diagnosis_confidence` float, `context` JSONB (typed per leg),
  `control_group` (denormalized, read-only), `superseded_by_case_id` self-FK,
  `recovery_type` + `recovered_amount` (**Module-7-only writes**), `opened_at`,
  `closed_at`. CHECKs: `diagnosis_confidence` ∈ [0,1] or NULL;
  `amount_at_risk >= 0`; `recovered_amount >= 0` or NULL. `IMPLEMENTED`.
- **Typed leg contexts** (`src/torque/contexts/`, Pydantic, `extra="forbid"`):
  `PaymentDegradationContext` (`decline_code?` — raw Razorpay `error_code`,
  `gateway`, `retry_count`, `is_hard_decline: bool | None` — **default `None`;
  ingestion leaves it unset and runs no classifier; Module 3 owns the hard/soft
  verdict**, D-058; `merged_abandonment_context: dict | None` — carries a
  superseded abandonment context on a §2.4 Merge, D-059),
  `CheckoutAbandonmentContext` (`cart_id`, `cart_value`,
  `drop_stage`, `payment_method_attempted` enum), `SubscriptionFailureContext`
  (`mandate_id`, `mandate_type` enum, `billing_cycle`, `subscription_id`).
  `B2B_RECEIVABLE` → **no context blob** (a non-empty dict is rejected).
  `validate_context()` is called by the flush guard on every case write.
  `IMPLEMENTED`.
- **`b2b_invoice`** (`B2BInvoice`) — UUID PK. `TenantScoped`. `case_id` nullable
  until triaged; many invoices → one case. `original_amount`,
  `outstanding_amount` `Numeric(14,2)` with CHECKs (`>= 0`,
  `outstanding <= original`), `days_overdue >= 0`, `gst_inclusive`,
  `payment_terms`. The bundling *trigger* is Module 2. `IMPLEMENTED` (schema).

### 2.3 Signal log
- **`event`** (`Event`) — UUID PK. `TenantScoped`. `type` free string,
  `idempotency_key` `UNIQUE` (= `X-Razorpay-Event-Id`, never payload-derived),
  `raw_payload` JSONB, `received_at`, `processed` bool (written `False` by M7a;
  nothing flips it until M7b's dispatch — D-056). Composite index
  `ix_event_merchant_type_received_at` `(merchant_id, type, received_at)` added
  in migration `0013` (M7a) for the Module 2 §2.4/§2.5 trailing-window scans.
  **The verifying HTTP endpoint `POST /webhooks/razorpay/{merchant_id}` is
  `IMPLEMENTED` (M7a)** — see §8.5. `IMPLEMENTED` (schema + endpoint +
  `verify_razorpay_signature`).

### 2.4 Event sourcing / history
- **`case_event`** (`CaseEvent`) — `event_seq_id` `BigInteger` autoincrement PK
  (**globally ordered, single sequence**). `case_id` FK, `counterparty_id`
  (reference only, nullable, **no PII**), `event_type` (`case_event_type` enum),
  `payload` JSONB (typed per type), `reasoning` Text (the explainability panel),
  `actor` (`actor` enum), `timestamp`. **NOT `TenantScoped` — has no
  `merchant_id` column** (tenancy reached via `case_id`). **No `action_id`
  column and no FK to `action`.** Append-only (see Invariants). `IMPLEMENTED`.
- **Eliminated, do not recreate:** `AuditLogEntry`, `PlaybookRun.step_history`,
  `Action.merged_case_ids`. Noted in `src/torque/models/__init__.py` docstring.

### 2.5 Retry-rail compliance entities (three structurally different postures)
- **`mac_code_registry`** (`MacCodeRegistry`) — composite PK `(network, mac_code)`.
  **Global scope**, not tenant-scoped. `tier` = `mac_tier` enum. Migration `0006`
  seeds **only the 13 locked rows** (`03, 21, 5C, 9G, 40, 41, 24–30`). Unseeded
  codes + Visa equivalents are `DEFERRED` (Part E item 1). `IMPLEMENTED`.
- **`card_retry_budget`** (`CardRetryBudget`) — UUID PK, `TenantScoped`,
  `UNIQUE(card_token_hash, merchant_id)`. `attempts_used_24h`/`_30d`,
  `hard_stop` bool, `hard_stop_reason` (`hard_stop_reason` enum). CHECK
  `hard_stop_reason_coherent` (hard_stop ⇔ reason set). Counter seeding at
  ingestion is Module 2 (`DEFERRED`). `IMPLEMENTED` (schema).
- **`upi_retry_budget`** (`UPIRetryBudget`) — UUID PK, `TenantScoped`,
  `UNIQUE(mandate_id, merchant_id)`. `mandate_id` is an **indexed String, not a
  FK** (no `Mandate` entity). `attempts_used`, `hard_cap` with
  `server_default=3` and **`CHECK (hard_cap = 3)`** (NPCI-enforced),
  `mandate_cancelled_at`. `permitted_execution_window` is **not a column** — it
  is a module constant + predicate. `IMPLEMENTED` (schema).
- **`nach_retry_policy`** (`NACHRetryPolicy`) — UUID PK, `TenantScoped`,
  `UNIQUE(mandate_id, merchant_id)`. `clearing_cycle_status`
  (`clearing_cycle_status` enum), `return_reason_code`, `retry_eligible_after`
  date, `dishonour_count_this_fy` (CHECK `>= 0`). NACH has **no NPCI cap** —
  ceiling is self-imposed, merchant-configurable, default 3 in `PolicyConfig`.
  `IMPLEMENTED` (schema).
- **`pre_debit_notification`** (`PreDebitNotification`) — UUID PK, `TenantScoped`.
  Per-attempt table (replaced the old single timestamp). `case_id` FK,
  `notified_at`, `covers_attempt_number` (CHECK `>= 1`), `channel`,
  `notified_amount` `Numeric(14,2)` (CHECK `>= 0`). Represents **Torque-initiated
  retry notifications only**. `IMPLEMENTED` (schema).

### 2.6 Systemic + rate card
- **`systemic_event`** (`SystemicEvent`) — UUID PK, `TenantScoped` (thresholds
  are per-merchant). `issuer_code?`, `network?` (`network` enum), `scope`
  (`systemic_scope` enum), `failure_rate_at_detection` `Numeric(12,4)`,
  `detected_at`, `resolved_at?`, `affected_case_count`. CHECK
  `issuer_specific_names_a_target` (a `NETWORK_WIDE` event may leave both null;
  `ISSUER_SPECIFIC` must name one). Detection job / rollups / case transitions
  are Module 2 (`DEFERRED`). `IMPLEMENTED` (schema + predicates).
- **`channel_rate_card`** (`ChannelRateCard`) — PK `channel` (**freeform String,
  no channel enum**). **Global scope.** `rate_per_unit` `Numeric(14,4)` (CHECK
  `>= 0`). Migration `0008` seeds `whatsapp`, `email`, `sms`. Consumption
  (`Action.cost`, Module 8 cost term) is `PLANNED`. `IMPLEMENTED` (schema + seed).

### 2.7 Playbooks
- **`playbook_identity`** (`PlaybookIdentity`) — PK `playbook_id` (human-readable
  slug). **Global**, effectively immutable. FK anchor for `playbook` versions
  and `merchant_playbook_config`. `IMPLEMENTED`.
- **`playbook`** (`Playbook`) — **composite PK `(playbook_id, version)`**.
  **Global — no `merchant_id`.** `leg_type`, nullable `mandate_type`
  discriminator (drives the UPI ≤3 rule), `trigger_condition` JSONB (freeform),
  `steps_graph` JSONB (validated against `StepGraph` at flush),
  `stopping_rules` JSONB (validated against `StoppingRules` at flush),
  `created_at` only — **no `updated_at`**. **Strict append-only**: Postgres
  trigger `playbook_no_mutate` (fn `torque_playbook_immutable`, migration `0009`)
  + flush guard. CHECK `version >= 1`. `IMPLEMENTED`.
- **`merchant_playbook_config`** (`MerchantPlaybookConfig`) — UUID PK,
  `TenantScoped`, `UNIQUE(merchant_id, playbook_id)`. FK `playbook_id` →
  `playbook_identity`. `stopping_rules_override` JSONB (partial; nullable = use
  base), `enabled` bool. Override validated at flush against the **latest**
  published `Playbook` version, including the UPI ≤3 ceiling. `enabled` does
  **not** participate in rule resolution. `IMPLEMENTED`.
- **`playbook_run`** (`PlaybookRun`) — UUID PK, `TenantScoped`. **Composite FK
  `(playbook_id, playbook_version)` → `playbook(playbook_id, version)`** — pins
  the version. `case_id` FK, `active_step_id` (**single pointer, nullable, NOT a
  log** — no `step_history`), `status` (`playbook_run_status` enum, default
  `RUNNING`). Run instantiation / step advance / status transitions are
  Module 4/5 (`PLANNED`). `IMPLEMENTED` (schema only).

### 2.8 Action ledger
- **`action`** (`Action`) — UUID PK, `TenantScoped`. `primary_case_id` FK
  (lead case). **`run_id` FK is nullable** (system/human-override activity not
  tied to a run). `action_type` (`action_type` enum), `channel?`, `content_sent?`
  Text (erasure-cascade target, orchestration `DEFERRED`), `executed_at?`,
  `outcome` (`action_outcome` enum), `block_reason?` (`block_reason` enum),
  `cost?` `Numeric(14,4)`. CHECKs: `outcome_block_reason_coherent`
  (`BLOCKED_BY_GUARDRAIL` ⇔ `block_reason` set), `executed_at_matches_outcome`
  (`BLOCKED_BY_GUARDRAIL` ⇔ `executed_at IS NULL`), `cost >= 0` or NULL.
  `IMPLEMENTED`.
- **`action_case`** (`ActionCase`) — composite PK `(action_id, case_id)`,
  `TenantScoped`. `is_primary` bool, `credit_weight` `Numeric(6,5)` (CHECK
  ∈ [0,1]). **Every `Action` has ≥ 1 `ActionCase` row** (Torque makes
  attribution universal — see `DECISIONS.md`). Guard-enforced: exactly one
  `is_primary`; its `case_id == Action.primary_case_id`; Σ `credit_weight` ==
  `Decimal("1.00000")` exactly; full set present in the same flush.
  `credit_weight` is mutable (Module 7 re-splits). `IMPLEMENTED`.

### 2.9 Recovery-signal entities
- **`payment_link`** (`PaymentLink`) — PK `link_id` (Razorpay `plink_...`,
  String, not UUID). `TenantScoped`. **`action_id` FK is nullable**
  (externally-originated / unattributed links; Torque does not invent a
  synthetic Action). `case_id` FK (not null). `status` (`payment_link_status`
  enum — **the one enum whose member names differ from values**, `ISSUED` vs
  `'issued'`; the column uses `values_callable=lambda e: [m.value for m in e]`
  because `0001` built the PG type from `.value`). `amount_paid` `Numeric(14,2)`
  (CHECK `>= 0`), `expires_at?`, `paid_at?`. CHECK
  `paid_status_matches_paid_at`: **`(status = 'paid') = (paid_at IS NOT NULL)`**
  — biconditional. Webhook-driven transitions are Module 2/7 (`PLANNED`).
  `IMPLEMENTED` (schema).
- **`promise_to_pay`** (`PromiseToPay`) — **surrogate UUID PK `promise_id`** +
  **`UNIQUE(captured_via)`** (enforces 0..1 promise per Action). `TenantScoped`.
  `case_id` FK, `captured_via` FK → `action.action_id` (not null),
  `promised_amount` `Numeric(14,2)` (CHECK `>= 0`), `promised_date`, `status`
  (`promise_status` enum, `server_default 'PENDING'`). **No `on_broken`
  column** — routing to the human queue is Module 6 runtime, not per-row config.
  Lifecycle enforced by `torque.promises` + flush guard. **No `CaseEvent` on a
  status change.** `IMPLEMENTED` (schema + lifecycle).

### 2.10 WhatsApp gate
- **`merchant_whatsapp_template`** (`MerchantWhatsAppTemplate`) — PK
  `template_id` (Meta/WABA id, String). `TenantScoped`. `template_name`,
  `category` (`whatsapp_template_category` enum: **`UTILITY` | `MARKETING`
  only**; `AUTHENTICATION` `DEFERRED`), **`approval_status` = plain
  `String(32)`, NOT an enum, no CHECK** (Meta owns/evolves the vocabulary),
  `leg_type` (reuses `leg_type` enum). Index
  **`ix_merchant_whatsapp_template_gate` on `(merchant_id, leg_type, category)`**
  — three columns, `approval_status` deliberately excluded. **No uniqueness
  beyond the PK.** The `whatsapp_template_category` PG type is created in
  migration `0012` (not `0001`). `IMPLEMENTED` (schema + predicate).

---

## 3. Enums (`src/torque/enums.py`)

All blueprint §4 enums are `StrEnum`. `ALL_ENUMS` tuple has **20** members.
Migration `0001` creates a native Postgres type for **19** of them (all that
existed at M1); `whatsapp_template_category` (#20) is created in migration `0012`.

`IMPLEMENTED`: `LegType`, `MandateType`, `CaseStatus`, `MacTier`, `Network`,
`ActionType`, `ActionOutcome`, `BlockReason`, `CaseEventType`, `Actor`,
`RecoveryType`, `PromiseStatus`, `PlaybookRunStatus`, `PaymentLinkStatus`,
`PaymentMethodAttempted`, `HardStopReason`, `ClearingCycleStatus`,
`SystemicScope`, `LanguagePref`, `WhatsAppTemplateCategory`.

Notes:
- **`PaymentLinkStatus`**: member name ≠ value (`ISSUED="issued"`, …). Handle
  with `values_callable` on any column that binds it.
- **`WhatsAppTemplateCategory`**: `UTILITY`, `MARKETING`. `AUTHENTICATION`
  intentionally omitted (`DEFERRED` — add via `ALTER TYPE ... ADD VALUE`).
- `root_cause_code` is **NOT** an enum here — owned by Module 3, `PLANNED`.

---

## 4. Multi-tenancy — `IMPLEMENTED` (application-layer)

- `TenantScoped` marker mixin (`db/base.py`). A model that inherits it must
  declare a non-null `merchant_id`.
- `TenantScope` (`db/scoped.py`) — a merchant-bound facade over a `Session`:
  `.select()` auto-filters `merchant_id`; `.get()` returns `None` for another
  merchant's row even on a direct PK lookup; `.add()` stamps `merchant_id` and
  raises `CrossTenantWriteError` on a mismatch; `.unscoped()` is the explicit,
  greppable escape hatch for global models.
- **Not tenant-scoped (global):** `Merchant`, `Counterparty`, `MacCodeRegistry`,
  `ChannelRateCard`, `PlaybookIdentity`, `Playbook`, **and `CaseEvent`** (which
  has no `merchant_id` at all — reached via `case_id`).
- Enforced at flush by `_guard_case` and the `TenantScope` facade. There is a
  flush guard path but the primary mechanism is: always go through `TenantScope`.
- `PLANNED` / `DEFERRED`: Postgres Row-Level Security (roadmap, blueprint §2.1).

---

## 5. PII / DPDP isolation — `IMPLEMENTED` (schema)

- Raw PII only on `counterparty` (`name`, `phone`, `email`).
- `Counterparty.redact_pii(source=...)` nulls the three and appends a
  `{"action": "erased", "scope": "pii", ...}` entry to `consent_log`.
- `CaseEvent.counterparty_id` and `Action.content_sent` reference only — no PII.
- `DEFERRED`: erasure-request intake UI/endpoint (blueprint Decision H / Part E
  item 7); cascade orchestration for `Action.content_sent` redaction.

---

## 6. State machines

### 6.1 `RevenueLeakCase.status` — `IMPLEMENTED` (`src/torque/state_machine.py`)
Transitions transcribed from blueprint §4 + Part C item 1. Entry point
`transition_case(session, case, target, *, trigger, actor, reasoning)` — validates
via `assert_transition`, writes the `STATUS_CHANGED` `CaseEvent` on the same
session, then mutates `case.status`.

```
DETECTED           -> {SYSTEMIC_HOLD, DIAGNOSING}
SYSTEMIC_HOLD      -> {DIAGNOSING}
DIAGNOSING         -> {PLAYBOOK_ACTIVE, ESCALATED_TO_HUMAN}   # ESCALATED path = Part C item 1
PLAYBOOK_ACTIVE    -> {RECOVERED, PARTIALLY_RECOVERED, EXHAUSTED, ESCALATED_TO_HUMAN, PAUSED, CANCELLED, SYSTEMIC_HOLD}
PAUSED             -> {PLAYBOOK_ACTIVE}
ESCALATED_TO_HUMAN -> {RECOVERED, PARTIALLY_RECOVERED, WRITTEN_OFF}
PARTIALLY_RECOVERED-> {}   # EXCEPT: + {PLAYBOOK_ACTIVE} iff leg_type == B2B_RECEIVABLE  (confirmed R4)
RECOVERED / EXHAUSTED / CANCELLED / WRITTEN_OFF -> {}   # terminal
```
`TERMINAL_STATUSES = {RECOVERED, EXHAUSTED, CANCELLED, WRITTEN_OFF}`;
`PARTIALLY_RECOVERED` is terminal for every leg **except** B2B.

**`PLAYBOOK_ACTIVE -> SYSTEMIC_HOLD` was ADDED in M7c** (U-01 #3, approved —
D-066). It is **legal but dormant**: `transition_case` executes it (trigger
`"systemic_network_wide"`, `STATUS_CHANGED` emitted, no `guards.py` change), but
M7c produces no `PLAYBOOK_ACTIVE` case and no code drives it — Module 5 owns
that. Resume is the existing `SYSTEMIC_HOLD -> DIAGNOSING`; there is no
`SYSTEMIC_HOLD -> PLAYBOOK_ACTIVE` edge.

**`UNRESOLVED` — 2 edges still deliberately NOT added** (module docstring):
- `DETECTED -> CANCELLED`, `DIAGNOSING -> CANCELLED` — needed by Module 7 §7.1.4
  (payment arrives before diagnosis finishes). Not in the §4 diagram.
`DIAGNOSING -> SYSTEMIC_HOLD` is also not present (not in §4, not in U-01) —
needs its own proposal if Module 3's `DIAGNOSING` cases must be sweepable.
See `UNRESOLVED.md` U-01.

### 6.2 `network_directive_tier` monotonicity — `IMPLEMENTED`
`apply_network_directive(session, case, *, mac_code, tier)` is the **only**
sanctioned writer. Rank `TIER_1_HARD_STOP(4) > TIER_3_INSTRUMENT_DEAD(3) >
TIER_2_CAPPED_RETRY(2) > TIMED_RETRY(1) > None(0)`. Equal or more restrictive =
OK; downgrade raises `MonotonicityViolation`. Also enforced defensively in the
flush guard (`_guard_case`) — a direct write outside
`network_directive_writer(session)` raises `OwnershipViolation`.
**`UNRESOLVED`**: Tier 1 vs Tier 3 precedence is a stated default, not
independently confirmed (blueprint §4 / Part E item 2).

### 6.3 `PromiseToPay.status` — `IMPLEMENTED` (`src/torque/promises.py`)
`PROMISE_TRANSITIONS`: `PENDING -> {KEPT, BROKEN}`; `KEPT`/`BROKEN` terminal.
`transition_promise(promise, target)` validates + mutates; **writes no
CaseEvent**. Same graph enforced independently by the flush guard
(`_guard_promise_to_pay`): a new row must resolve to `PENDING` (a pre-flush
`status is None` counts as `PENDING`); a status change on an existing row must be
a legal transition.

### 6.4 `PlaybookRun.status` — `PLANNED` (runtime transitions)
The enum exists and the column defaults to `RUNNING`. There is **no** transition
logic — `RUNNING → PAUSED/COMPLETED/HALTED_BY_GUARDRAIL/ESCALATED/CANCELLED` is
Module 4/5.

### 6.5 `PaymentLink.status` / `B2BInvoice` — `PLANNED` (runtime)
Enum + coherence CHECK only. Webhook-driven transitions are Module 2/7.

---

## 7. Event model — `IMPLEMENTED`

- **`CaseEvent` is the sole history mechanism.** Append-only, two-layer
  enforcement: Postgres trigger `case_event_no_mutate` (fn
  `torque_case_event_immutable`, migration `0005`) raising on UPDATE/DELETE, plus
  the `before_flush` guard rejecting dirty/deleted `CaseEvent` instances.
- **10 locked payload schemas** (`src/torque/events/payloads.py`, Pydantic
  `extra="forbid"`): `STATUS_CHANGED`, `DIAGNOSIS_COMPLETED`, `ACTION_EXECUTED`,
  `ACTION_BLOCKED`, `NETWORK_DIRECTIVE_RECEIVED`, `PROMISE_CAPTURED`,
  `PAYMENT_RECONCILED`, `SYSTEMIC_HOLD_APPLIED`, `HUMAN_RESOLVED`,
  `STEP_TRANSITIONED`. Import-time assertion fails loudly if `CaseEventType` and
  the registry drift. `validate_payload()` is the enforcement point;
  `append_case_event()` calls it. **No `event_type` may be written without a
  matching schema.**
- **`STEP_TRANSITIONED` payload shape is `UNRESOLVED`** (blueprint Part E item 3
  — provisional; flagged in the module docstring). See `UNRESOLVED.md` #2.
- `ACTION_EXECUTED` payload: `channel` and `cost` are **nullable** (intentional
  deviation — see `DECISIONS.md`).

---

## 8. Action / execution model

- **Atomic write primitive — `IMPLEMENTED`** (`src/torque/events/case_event_writer.py`):
  - `atomic(session)` — one transaction; nests via `begin_nested()` (SAVEPOINT)
    if already in a transaction, else `session.begin()`.
  - `append_case_event(...)` — validates payload, stages the `CaseEvent`.
  - `write_action_and_event(...)` — the **single sanctioned path** to write an
    `Action`. In one transaction persists: the `Action`; its `ActionCase`
    row(s) (`attributions=None` → one `is_primary` row at `credit_weight =
    Decimal("1.00000")`; `attributions=[Attribution(...)]` → multi-case);
    and one correlated `CaseEvent` (`ACTION_EXECUTED`, or `ACTION_BLOCKED` when
    `outcome == BLOCKED_BY_GUARDRAIL`) carrying `action_id` as a **string in the
    payload** — the only Action↔CaseEvent link (no column, no FK).
  - `Attribution` is a frozen dataclass `(case_id, is_primary, credit_weight)`.
- **Guardrail checks / channel adapters / retry execution / Temporal workflow —
  `PLANNED`** (Module 5/6). None of `RETRY_PAYMENT`, `SEND_WHATSAPP`,
  `GENERATE_PAYMENT_LINK`, `LOG_PROMISE`, etc. have any execution path.
- **`GuardrailEngine.check()` — `PLANNED`** (Module 6). The pure predicates it
  will call (`torque.compliance.*`) exist; the engine, ordering, short-circuit
  logic, and `Action.outcome = BLOCKED_BY_GUARDRAIL` production do not.

---

## 8A. HTTP surface — `IMPLEMENTED` (M7a), the first and only routes

`src/torque/api/` (added M7a — the repo's first HTTP code):

- **`app.py`** — `create_app() -> FastAPI`. Routes only, no startup work.
  `GET /health` → `{"status": "ok"}`. Includes the webhook router. FastAPI
  auto-docs (`/docs`, `/redoc`, `/openapi.json`) left enabled.
- **`deps.py`** — `get_db()` request dependency: yields a `SessionLocal` session
  (guards wired), commits on clean return, rolls back on exception, always
  closes. Overridden in tests to yield the harness's joined-transaction session.
- **`webhooks.py`** — `POST /webhooks/razorpay/{merchant_id}`. The §2.2
  verify-before-parse pipeline: `await request.body()` (no Pydantic body model,
  so the raw bytes are intact) → `verify_razorpay_signature(raw, header,
  Settings.active_razorpay_webhook_secret())` (constant-time; mode from
  `Settings.razorpay_webhook_mode`, never tries both secrets) → mismatch/missing/
  unset-secret ⇒ empty `200`, zero side effects → parse → non-object body or
  missing `X-Razorpay-Event-Id` or unknown merchant ⇒ empty `200`, no row →
  `SELECT` on `Event.idempotency_key`; hit ⇒ empty `200`, no reprocess → else
  `TenantScope(session, merchant_id).add(Event(type=payload["event"] or
  "unknown", idempotency_key=<header>, raw_payload=<parsed>, processed=False))`,
  `flush()` (concurrent-insert `IntegrityError` ⇒ treated as duplicate, `200`).
  See INV-23.
- **`src/torque/__main__.py`** — `python -m torque` → `uvicorn` (`--factory`),
  dev/preview only.
- Deps added: `fastapi`, `uvicorn[standard]` (runtime); `httpx` (dev, TestClient).

**Not here:** any other route; auth on `/health`; per-merchant secrets.

---

## 8B. Signal ingestion logic — `torque.ingestion` — `IMPLEMENTED` (M7b Leg 1 + M7c systemic)

`src/torque/ingestion/` (M7b + M7c). The post-`Event` half of Module 2, Leg 1
only, plus the leg-agnostic §2.5 systemic layer. **Celery + Redis** (broker only,
no result backend — D-057 / U-07 inbound half) + **Celery beat** for the 60s job
(D-064). No migration — pure logic over existing tables + one approved
state-machine edge.

- **`celery_app.py`** — `Celery("torque")`, `broker = Settings.redis_url` (host
  6389), `task_ignore_result`, eager flags from
  `Settings.celery_task_always_eager` (test harness only);
  `conf.beat_schedule["systemic-detection"]` → `torque.ingestion.detect_systemic`
  every `60.0`s (M7c). Dev: `celery -A torque.ingestion.celery_app:celery_app
  worker` and `... beat`.
- **`tasks.py`** — `resolve_buffered_event_task(event_id)` (M7b; one
  `session_scope()` via seam `_session_scope`, calls `buffer.resolve_buffered_event`)
  and `detect_systemic_task()` (M7c; one `session_scope()`, calls
  `systemic.run_systemic_detection(now=utcnow())`). Enqueued by `api/webhooks.py`
  for `payment.failed` with `countdown = 90`; the systemic task by beat.
- **`buffer.py`** — `resolve_buffered_event(session, *, event_id)`. `NOOP`
  (Event gone / already `processed` / not `payment.failed` / case exists);
  `SELF_RECOVERED` (a `payment.captured` for the same `payment_id`/`order_id`,
  `received_at >= failure.received_at` → `Event.processed = True`, no case);
  else `create_or_attach_case`. `payment_failure_buffer_seconds()` = 90.
- **`cases.py`** — `create_or_attach_case`: idempotent on `source_event_id`;
  `resolve_counterparty`; `find_supersedable_case`; insert
  `RevenueLeakCase(PAYMENT_DEGRADATION, DETECTED, …)` via `TenantScope`;
  `sync_control_group`; on a Merge → set the abandonment case's
  `superseded_by_case_id` (status untouched) + copy its context into
  `context["merged_abandonment_context"]`; `_seed_card_retry_budget` for card
  payments (seed-to-1, idempotent; the inherited `card_token_hash` column holds
  the Razorpay tokenised ref `COALESCE(token_id, card_id)` — **no PAN, no
  hashing in M7b**, D-061); `Event.processed = True`. **All of the above +
  `Event.processed` commit/roll back as one transaction** — the Celery task's
  single `session_scope()`; `create_or_attach_case` only `flush()`es.
- **`dedup.py`** — `find_supersedable_case`: open non-terminal
  `CHECKOUT_ABANDONMENT`, same `(merchant_id, counterparty_id)`,
  `context.cart_id == order_id`, within `PolicyConfig.cross_leg_dedup_window_hours`
  (2h). **Live direction only** (reverse deferred with Leg 2 — D-060).
- **`identity.py`** — `resolve_counterparty`: exact phone → exact email →
  create (`Counterparty` global via raw session; `Merchant_Counterparty` via
  `TenantScope`; safe consent defaults). Known dup-identity limitation — D-062.
- **`payloads.py`** — pure Razorpay `payment.*` extractors.
- **`outcomes.py`** — `BufferOutcome` enum (`NOOP` / `SELF_RECOVERED` /
  `CASE_CREATED` / `CASE_MERGED`).
- **`systemic.py`** (M7c) — the §2.5 `NETWORK_WIDE` job.
  `run_systemic_detection(session, *, now=None)` iterates merchants with
  `payment.failed` in the detection window ∪ merchants with an active
  `SystemicEvent`; `_detect_and_hold` (trailing-10-min failures/min vs. a
  trailing-7-day baseline that **excludes** the live window → `systemic_threshold_breached`
  → `SystemicEvent(NETWORK_WIDE, issuer_code=None, network=None)` + sweep open
  `DETECTED` cases via `_hold_case`); `_check_and_resolve` (recompute trailing-
  sustain rate → `systemic_resolved` → `resolved_at` + batch `SYSTEMIC_HOLD →
  DIAGNOSING`, `systemic_event_id` left set); `_hold_case` (set FK →
  `transition_case(→ SYSTEMIC_HOLD, trigger="systemic_network_wide")` →
  `SYSTEMIC_HOLD_APPLIED` `CaseEvent`); `apply_active_hold_if_any(session, case)`
  is the §2.7 hook called by `cases.create_or_attach_case`. Idempotent
  (≤1 active event/merchant; sweep filters `systemic_event_id IS NULL`).
  `cases.py` gained one additive call to `apply_active_hold_if_any` before
  `event.processed = True` — no-active-event path is byte-for-byte M7b.

Invariants: INV-24 (buffer → no case on self-recovery), INV-25 (Merge:
one-directional, lossless, idempotent), INV-26 (every ingestion case has a
counterparty), **INV-27** (systemic detection idempotent), **INV-28** (held case
carries `systemic_event_id`), **INV-29** (resolution touches only its own held
cases). All `HELPER`-class (function-enforced + tested), not `ORM-GUARD`.

**Not here:** Leg 2/3/4 ingestion; the `subscription.charged.failed` 30s buffer;
reverse Merge; `ISSUER_SPECIFIC` systemic detection (U-08); `UPIRetryBudget` seeding;
per-decline budget increments; token hashing; dispatch to Module 3; a
`docker-compose` worker service.

---

## 9. Attribution model — `IMPLEMENTED` (schema + invariant), `PLANNED` (computation)

- `ActionCase(action_id, case_id, is_primary, credit_weight)` — universal (≥1 per
  Action). Σ `credit_weight` == 1.00000 exact, guard-enforced.
- **`PLANNED`**: Module 7 matching logic (`PaymentLink` direct match →
  `AGENT_ASSISTED`; indirect amount match + 24h action window; multi-case
  proportional split; no-match → `CANCELLED`/`SELF_RECOVERED`); writing
  `RevenueLeakCase.recovery_type` / `recovered_amount` (guarded by
  `module7_writer(session)` — the context manager exists, no caller does).

---

## 10. Compliance model — pure predicates `IMPLEMENTED`, enforcement `PLANNED`

`src/torque/compliance/` — all side-effect-free:
- `mac_registry.tier_for(session, network, mac_code)` → `MacTier | None`
  (`None` on unseeded; the "default TIER_2 + flag a CaseEvent" fallback is
  Module 5, `DEFERRED`).
- `pre_debit.gap_satisfied(session, *, case_id, next_attempt_number, now)` —
  the RBI ≥24h EXISTS check. `PRE_DEBIT_MIN_GAP_HOURS = 24` (a legal floor, not
  a `PolicyConfig` tunable).
- `retry_rails` — `card_retry_within_budget`, `upi_attempt_gate_open`,
  `within_upi_execution_window` (closed peak intervals `10:00–13:00`,
  `17:00–21:30` IST; aware→IST, naive assumed IST wall-clock),
  `nach_retry_eligible`. Constants: `CARD_ATTEMPTS_24H_CAP=10`,
  `CARD_ATTEMPTS_30D_CAP=35`, `UPI_AUTOPAY_HARD_CAP=3`, `IST`,
  `UPI_PEAK_WINDOWS_IST`.
- `systemic.systemic_threshold_breached(...)` (compound: spike ≥ multiplier×
  baseline AND baseline ≥ N AND absolute ≥ M) / `systemic_resolved(...)`
  (sustain window). Numeric N/M/multiplier come from `PolicyConfig` — the
  defaults there are **unverified placeholders** (`DEFERRED` tuning).
- `whatsapp.approved_template_exists(session, *, merchant_id, leg_type, category)`
  — EXISTS query; passes **iff** `approval_status == WHATSAPP_APPROVED`
  (`"APPROVED"`, exact, case-sensitive). Everything else fails closed.
- **`PLANNED` / `DEFERRED`**: quiet-hours enforcement, the Outreach Coordinator
  (priority formula, merge, defer, open-conversation), escalation-ceiling
  handling, the human queue, `GuardrailEngine` (all Module 6).

---

## 11. Database architecture — `IMPLEMENTED`

- **PostgreSQL 16.** Native ENUM types (created in `0001`, one added in `0012`).
- **Deterministic naming** (`db/base.py` `NAMING_CONVENTION`) for every ix / uq /
  ck / fk / pk — keeps migrations reviewable.
- **Triggers:** `case_event_no_mutate` (0005), `playbook_no_mutate` (0009).
- **CHECK constraints** carry coherence rules Postgres *can* express (biconditionals,
  ranges, locked constants). Cross-row rules (Σ credit_weight, ActionCase set
  shape, append-only for ORM path, context typing) live in the **flush guard**
  because a CHECK cannot express them.
- **Migrations `0001`–`0013`**, linear chain, one/two per milestone (`0013` is
  M7a — index only, no table/column/enum). Roundtrip
  (`upgrade→downgrade→upgrade`) tested. Enum types dropped in `downgrade`.
- **Test DB harness:** `tests/conftest.py` drops/recreates `public` schema in
  `torque_test`, runs `alembic upgrade head`, then joins each test to an outer
  transaction rolled back afterward (`join_transaction_mode="create_savepoint"`).
- `DEFERRED`: RLS; partitioning; any read-model / projection tables.

---

## 12. Key invariants (summary — full catalogue in `INVARIANTS.md`)

All `IMPLEMENTED`:
1. Tenant isolation — `TenantScope` + guard.
2. `CaseEvent` append-only — trigger + guard.
3. `Playbook` version immutable — trigger + guard.
4. `RevenueLeakCase.context` typed on every flush — guard calls `validate_context`.
5. `network_directive_tier` most-restrictive-wins — `apply_network_directive` + guard.
6. `recovery_type` / `recovered_amount` writable only via `module7_writer` — guard.
7. `RevenueLeakCase.status` transitions restricted to the locked graph — `transition_case`.
8. `MerchantCounterparty.in_control_cohort` assigned once — `assign_cohort`.
9. Playbook `steps_graph` / `stopping_rules` valid + normalized on insert — guard.
10. `MerchantPlaybookConfig` override valid against latest version, incl. UPI ≤3 — guard.
11. Every `Action` has ≥1 `ActionCase`; exactly one `is_primary`; its `case_id`
    == `primary_case_id`; Σ `credit_weight` == 1.00000 — guard.
12. Action↔CaseEvent atomicity: a new `Action` needs a same-flush correlated
    `CaseEvent` with matching `payload.action_id` — guard.
13. `PromiseToPay` created `PENDING`; transitions `PENDING→{KEPT,BROKEN}` only — `promises` + guard.
14. `UPIRetryBudget.hard_cap == 3` — CHECK.
15. Coherence CHECKs: `card_retry_budget.hard_stop_reason_coherent`,
    `action.outcome_block_reason_coherent`, `action.executed_at_matches_outcome`,
    `payment_link.paid_status_matches_paid_at`, `systemic_event.issuer_specific_names_a_target`.
16. `Event.idempotency_key` UNIQUE; `PromiseToPay` `UNIQUE(captured_via)`;
    various `UNIQUE(merchant_id, ...)`.
17. WhatsApp gate passes only on exact `approval_status == "APPROVED"` (fail-closed).

---

## 13. Dependencies between components

```
enums.py  <-  (everything)
db/base.py  <-  models/*, db/scoped.py
config.py  <-  db/session.py (DB URL), later modules (PolicyConfig)
contexts/  <-  models/guards.py (validate_context on case flush)
events/payloads.py  <-  events/case_event_writer.py, state_machine.py
events/case_event_writer.py  <-  state_machine.py (append_case_event), make_action test fixture
playbooks/  <-  models/guards.py (validate_playbook / validate_merchant_playbook_config)
compliance/retry_rails.py (UPI_AUTOPAY_HARD_CAP)  <-  playbooks/validation.py (defense-in-depth)
promises.py  <-  models/guards.py (_guard_promise_to_pay)
models/guards.py  <-  db/session.py (register_guards onto SessionLocal)
state_machine.py  <-  models/guards.py (network_directive_writer, tier_rank)   # note: state_machine imports FROM guards
api/deps.py  <-  db/session.py (SessionLocal)                                  # M7a
api/webhooks.py  <-  api/deps.py, config.py (Settings), db/scoped.py (TenantScope),
                     models (Event, Merchant), security/razorpay_signature,
                     ingestion/buffer + ingestion/tasks (enqueue)               # M7a + M7b
api/app.py  <-  api/webhooks.py ;  __main__.py  <-  api/app.py (uvicorn factory)
ingestion/celery_app.py  <-  config.py (redis_url) ; beat_schedule -> detect_systemic  # M7b + M7c
ingestion/tasks.py  <-  celery_app, db/session ; detect_systemic_task -> ingestion/systemic  # M7c
ingestion/buffer.py  <-  ingestion/cases, ingestion/payloads, ingestion/outcomes, config (policy)
ingestion/cases.py  <-  ingestion/{payloads,identity,dedup,outcomes,systemic}, db/scoped,
                        state_machine (sync_control_group), models (Event, RevenueLeakCase, CardRetryBudget)
ingestion/dedup.py  <-  state_machine (is_terminal), config (policy), models (RevenueLeakCase)
ingestion/systemic.py  <-  compliance/systemic (predicates), state_machine (transition_case),   # M7c
                        events (append_case_event), db/scoped, config (policy),
                        models (Event, RevenueLeakCase, SystemicEvent)
```
(`state_machine.py` is imported FROM by `ingestion/{cases,dedup,systemic}` — read-only.
`state_machine.py` was byte-stable M1→M7b; **M7c added exactly one edge**
`PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` + a docstring cleanup, nothing else — D-066.)

Circular-import care points (already handled in code, do not "fix"):
- `models/guards.py` imports `Action` / `ActionCase` / `PromiseToPay` **lazily
  inside** `_before_flush` (models `__init__` imports `action` first, and
  `db.session` pulls in `guards` mid-import).
- `contexts/registry.py` imports the concrete context models at the **bottom** of
  the file.
- `state_machine.py` imports several names **from** `models/guards.py`.

---

## 14. What is explicitly NOT here

See `DEFERRED.md` for the full register. Highlights: the **only** HTTP routes are
`GET /health` and `POST /webhooks/razorpay/{merchant_id}` (M7a) — no other
endpoint, no auth layer. **Celery + Redis** (broker only) + **Celery beat** run
the M7b inbound buffer and the M7c §2.5 job — but no Temporal, no `PlaybookRun`
workflow engine, no Postgres-polling job table (U-07 remaining half), no
`docker-compose` worker/beat service. No Leg 2/3/4 ingestion, no
`subscription.charged.failed` buffer, no reverse cross-leg Merge, **no
`ISSUER_SPECIFIC` systemic detection** (U-08; `NETWORK_WIDE` is done — M7c), no
`UPIRetryBudget` seeding, no per-decline budget increments, no card-token
hashing, no `Event`→Diagnosis dispatch, no code that drives
`PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` (edge is legal but dormant). No diagnosis, no
playbook runtime traversal, no channel adapters, no
`GuardrailEngine`, no Outreach Coordinator, no reconciliation, no scoring, no
reporting, no UI, no `MacCodeRegistry` full seed, no `root_cause_code` enum.
