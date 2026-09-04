# ARCHITECTURE SNAPSHOT

State as of Module 2 completion (Milestone 7 commit `2a35786` + uncommitted M8 +
uncommitted Module-2 completion run). Derived documentation — verify against
code before relying on any single line.

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
| 2 — Signal Ingestion | webhook intake, signature verify, idempotency, out-of-order buffer, cross-leg dedup, systemic detection job | **`IMPLEMENTED` (Module 2 complete)** — all four legs: Leg 1 `payment.failed` (90s buffer, `PAYMENT_DEGRADATION`), Leg 3 `subscription.charged.failed` (30s buffer, `SUBSCRIPTION_FAILURE`, UPI/NACH/Card rail seeding), Leg 2 `checkout.abandoned` (signed `/internal` injection endpoint, no buffer, `CHECKOUT_ABANDONMENT`), Leg 4 `invoice.overdue` (no buffer, `B2BInvoice` + §3 grouping, `B2B_RECEIVABLE`); **bidirectional** §2.4 cross-leg Merge; §2.5 `NETWORK_WIDE` systemic detection + hold/resume + §2.7 hold-on-ingest across all legs; `PLAYBOOK_ACTIVE→SYSTEMIC_HOLD` edge added (dormant). Celery/Redis broker-only + Celery beat. Remaining *refinements* (not blockers): `ISSUER_SPECIFIC` detection (U-08); systemic rollup over subscription failures (D-073); a real storefront pixel (Part D item 1); dispatch to Module 3 |
| 3 — Diagnosis Engine | root-cause classification + confidence; owns `root_cause_code` enum | **`IMPLEMENTED` (Module 3 complete)** — `torque.diagnosis` package: rule-based per-leg classification (§3.2), `T = 0.65` confidence routing to `PLAYBOOK_ACTIVE`/`ESCALATED_TO_HUMAN` (§3.3), `is_hard_decline` set here (D-058/D-084), `suggested_timing_adjustment` (§3.4, new col), one `DIAGNOSIS_COMPLETED` event per case, idempotent + atomic + tenant-scoped. Auto-dispatch from Module 2 (D-080) and §5.3 first-touch MAC lookup (D-083) deferred. See §8C |
| 4 — Policy & Playbook Engine | root cause → bounded action graph; playbook authoring/validation (validation part `IMPLEMENTED` in M4) | **`IMPLEMENTED` (Module 4 complete)** — `torque.policy` package: the eleven-playbook §4.1 catalog (ORM-seeded, D-085), root-cause→playbook selection, version-pinned `PlaybookRun` instantiation for `PLAYBOOK_ACTIVE` cases (no-playbook/disabled → `ESCALATED_TO_HUMAN`, D-086), pure graph-reading traversal rules, payday-override policy gate (§4.3), `multi_case_template` contract (§4.4). Runtime execution/timing/guardrails/Temporal are Module 5. See §8D |
| 5 — Execution / Orchestration | runtime graph execution, retry-budget enforcement, atomic Action+CaseEvent write, timing/allowed-hours/payday, durable driver | **`IMPLEMENTED` (Module 5 complete)** — `torque.execution`: the §5.6 **Postgres-polling** driver (`scheduled_job` + 10 s/60 s beat pollers, `FOR UPDATE SKIP LOCKED`) chosen over Temporal (D-090); `execute_due_job` runs the §5.1 loop (guardrails §5.2 → executor stub §5.4 → atomic Action+CaseEvent → `STEP_TRANSITIONED` → advance `active_step_id`); timing D-025; Card/UPI/NACH consumption; U-02 settled (D-091). Real channel adapters + Outreach Coordinator + WhatsApp gate are Module 6 (D-092). See §8E |
| 6 — Compliance & Cross-Leg Guardrail Engine | `GuardrailEngine.check()`, Outreach Coordinator, escalation ceiling, human queue | **`IMPLEMENTED` (Module 6 complete)** — `torque.coordination` package: the `GuardrailEngine` facade (§6.2, returns the four-way `GuardDecision` — D-097); the Outreach Coordinator (4h cross-leg quiet period, live merge in the poll batch, defer, open-conversation — Part A §5); the full WhatsApp gate (opt-in + approved UTILITY template + open-conversation suspend); §6.3 escalation-ceiling → `ESCALATED_TO_HUMAN` in the runner tick; the persistent `human_queue` table (migration 0016) + three feeders. `priority()` is the Module 8 seam (D-098). See §8F |
| 7 — Reconciliation & Attribution | match payments → cases, `AGENT_ASSISTED` vs `SELF_RECOVERED`, write `credit_weight` | **`IMPLEMENTED` (Module 7 complete)** — `torque.reconciliation`: `reconcile_event()` matches a verified success `Event` (§7.1: direct `PaymentLink` → indirect `(merchant, cp, amount)` → merged-set re-split / `AMBIGUOUS` → `DETECTED/DIAGNOSING → CANCELLED` self-pay); closes cases (§7.2: `RECOVERED` / B2B `PARTIALLY_RECOVERED` with invoice waterfall) + `PAYMENT_RECONCILED`; `recovery_type` / `recovered_amount` via `module7_writer`. Wired into `webhooks.py` (D-104). **`state_machine.py` gained the two U-01 edges** (D-103); no migration. See §8G |
| 8 — Recovery Scoring | `(probability × amount) ÷ cost`, cold-start lookup | **`IMPLEMENTED` (Module 8 complete)** — `torque.scoring` package: `cold_start_probability` (Decision F's exact 8-value table as a live function), `warm_start_multiplier` (§8.2 linear map, clamped 0.5×–1.3×, D-110), `compute_cost` (forward `ChannelRateCard` sum for the next playbook step, zero-cost floors — D-111), `compute_recovery_score` / `RecoveryScore` (the one formula + §8.7 explainability). Persisted on `revenue_leak_case.recovery_score` / `_breakdown` / `_updated_at` (migration **0017**, D-109). Recompute on creation / diagnosis / daily (D-112). `priority()` seam now returns it (D-113). See §8H |
| 9 — Reporting & Measurement | ₹ recovered, recovery rate, by leg/intervention/outcome/time, exception list, case drill-down | **`IMPLEMENTED` (Module 9 complete)** — `torque.reporting` (`metrics.py` derivations + `schemas.py` pydantic contract) + read-only `torque.api.reporting` router (8 `GET` endpoints). Outcome-based (D-116: `recovered_amount` = `recovery_type != SELF_RECOVERED`; `SELF_RECOVERED` reported separately). **No migration** — pure read/derive over the domain tables (D-114). Module 7 stays authoritative for attribution. Incrementality lift / Wilson CI / SUTVA-adjusted lift **deferred** (D-121 / U-10). See §8I |
| 10 — UI/UX | merchant dashboard, agent console, demo surface | **`IMPLEMENTED` (Module 10 complete)** — a hand-written static SPA (`src/torque/ui/static/`) mounted at `/ui` by `create_app()` (one process, `uv run python -m torque` — D-122); `torque.agent_console` (human resolve/pause/unpause — INV-59, migration **0018** for `escalation_resolution` — D-123); `torque.demo` (deterministic `acc_demo` seed + one-click Decision-K scenarios — D-124/125); Module 9 reporting gains `top-at-risk` / `human-queue` / `activity` + the case-detail score breakdown. `state_machine.py` unchanged; `guards.py` gains `human_resolution_writer`. See §8J |
| 11 — Tech Stack & Infra | Temporal / BullMQ / polling fallback | `PLANNED` |
| 12 — Build Roadmap | phase plan (no calendar dates — Part D item 3) | `PLANNED` / `UNRESOLVED` |
| 13 — Demo Script | judging narrative | `PLANNED` |

---

## 2. Entities (blueprint §3) — all `IMPLEMENTED`

25 tables (Module 5 added `scheduled_job`; Module 6 added `human_queue`). One ORM
file each under `src/torque/models/`. All are typed SQLAlchemy 2.0 models on the
shared `Base` with `NAMING_CONVENTION`.

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
  `diagnosis_confidence` float (**written by Module 3**),
  `suggested_timing_adjustment` `VARCHAR(64)` nullable (**§3.4 payday-cycle hint,
  written by Module 3**, migration `0014`, D-079), `context` JSONB (typed per
  leg), `control_group` (denormalized, read-only), `superseded_by_case_id`
  self-FK, `recovery_type` + `recovered_amount` (**Module-7-only writes**),
  `opened_at`, `closed_at`. CHECKs: `diagnosis_confidence` ∈ [0,1] or NULL;
  `amount_at_risk >= 0`; `recovered_amount >= 0` or NULL. `root_cause_code` /
  `root_cause_label` / `diagnosis_confidence` / `suggested_timing_adjustment` are
  written by Module 3 (§9); `is_hard_decline` (in `context`) likewise. `IMPLEMENTED`.
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
  `>= 0`). Migration `0008` seeds `whatsapp` 0.8850, `email` 0.0100, `sms`
  0.2000. **Module 8's cost term (`torque.scoring.cost`) reads it** — Σ
  `rate_per_unit` for the next playbook step's channel(s); `"payment_link"` and
  no-channel steps have no row and floor (D-111). `Action.cost` population by
  Module 5 is still `PLANNED`. `IMPLEMENTED` (schema + seed + Module 8 use).

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
- `root_cause_code` is **NOT** an enum in `enums.py` — owned by Module 3. Now
  `IMPLEMENTED` as `torque.diagnosis.root_causes.RootCauseCode` (a `StrEnum`, 23
  §3.1 members; `.value` persisted to the plain `String` column — the DB column
  stays `String`, deliberately not a Postgres enum, so §3.1 refinement needs no
  migration). See §8C.

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

## 8A. HTTP surface — `IMPLEMENTED` — Module 2 ingestion + Module 9/10 reporting + Module 10 console/demo/UI

`src/torque/api/` (M7a + the Module-2 completion run + Modules 9–10):

- **`app.py`** — `create_app() -> FastAPI`. Routes only, no startup work.
  `GET /health` → `{"status": "ok"}`. Includes the webhook, checkout-injection,
  reporting, **agent-console**, and **demo** routers; **`mount_ui(app)`** attaches
  the static SPA at `/ui`. FastAPI auto-docs left enabled.
- **`agent_console.py`** (Module 10) — `POST /agent-console/{merchant_id}/cases/
  {case_id}/{resolve|pause|unpause}`. Thin: HTTP ↔ `torque.agent_console.resolve`;
  `CaseNotFoundError` → 404, `HumanResolutionError` / `IllegalTransitionError` →
  409. `get_db` commits a successful override. INV-59.
- **`demo.py`** (Module 10) — `POST /demo/seed?reset=`, `GET /demo/scenarios`,
  `POST /demo/inject/{key}`, `GET /demo/merchant`. Operates only on `acc_demo`.
- **`ui.py`** (Module 10) — `GET /` → 307 `/ui/`; `mount_ui` = `StaticFiles(
  directory=src/torque/ui/static, html=True)` at `/ui`. Hash-router SPA; no
  Node, no build (D-122).
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
- **`checkout_injection.py`** — `POST /internal/checkout-abandoned/{merchant_id}`
  (Module-2 completion run). The §2.6 signed synthetic injection endpoint —
  identical verify-before-parse contract to `webhooks.py` (INV-23/INV-34) with a
  **dedicated** `Settings.checkout_injection_secret` and `X-Torque-Signature` /
  `X-Torque-Event-Id` headers; writes one `Event(type="checkout.abandoned")` +
  enqueues `create_checkout_case_task`. D-074.
- **`reporting.py`** (Module 9) — a **read-only** `APIRouter`
  (`prefix="/reports/{merchant_id}"`, `tags=["reporting"]`). 8 `GET` endpoints:
  `/summary`, `/report` (the §9.4 batch bundle), `/by-intervention`
  (`?by=leg|action_type`), `/over-time` (`?bucket=day|week|month`,
  `?closed_from`/`?closed_to`), `/exceptions`, `/cases` (paginated, `?leg`
  `?status` `?opened_from`/`?opened_to`), `/cases/{case_id}`,
  `/cases/{case_id}/events` (the explainability stream). `_require_merchant` →
  404 for an unknown merchant; a cross-tenant `case_id` → 404 (the metrics layer
  returns `None`); bad `leg`/`status` → 422. Delegates to `torque.reporting.
  metrics` — no business logic in the router. `get_db` still commits on clean
  return, but every handler issues only `SELECT`s.
- **`src/torque/__main__.py`** — `python -m torque` → `uvicorn` (`--factory`),
  dev/preview only.
- Deps: `fastapi`, `uvicorn[standard]` (runtime); `httpx` (dev, TestClient).

**Not here:** any other route; auth on `/health`; per-merchant secrets; a real
storefront pixel (the injection endpoint is the demo-scope default — Part D
item 1).

---

## 8B. Signal ingestion logic — `torque.ingestion` — `IMPLEMENTED` (all four legs + systemic)

`src/torque/ingestion/` (M7b + M7c + M8 + the Module-2 completion run). The
post-`Event` half of Module 2 for **all four legs**, plus the leg-agnostic §2.5
systemic layer. **Celery + Redis** (broker only, no result backend — D-057 / U-07
inbound half) + **Celery beat** for the 60s job (D-064). No migration — pure
logic over existing tables + the one M7c state-machine edge.

One task per ingestion path (`tasks.py`, each = one `session_scope()` via the
`_session_scope` test seam): `resolve_buffered_event_task` (Leg 1, `countdown=90`),
`resolve_subscription_buffered_event_task` (Leg 3, `countdown=30`),
`create_checkout_case_task` (Leg 2, immediate), `ingest_invoice_task` (Leg 4,
immediate), `detect_systemic_task` (beat, 60s).

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
- **`dedup.py`** — **bidirectional** §2.4 (D-075). `find_supersedable_case`
  (forward: a `payment.failed` arriving second → open non-terminal
  `CHECKOUT_ABANDONMENT` case, `context.cart_id == order_id`) and
  `find_supersedable_payment_case` (reverse: a `checkout.abandoned` arriving
  second → open non-terminal `PAYMENT_DEGRADATION` case whose
  `source_event.raw_payload` `order_id == cart_id`). Both: same
  `(merchant_id, counterparty_id)`, `superseded_by_case_id IS NULL`, within
  `PolicyConfig.cross_leg_dedup_window_hours` (2h), Python id match, no JSONB
  index.
- **`identity.py`** — `resolve_counterparty`: exact phone → exact email →
  create (`Counterparty` global via raw session; `Merchant_Counterparty` via
  `TenantScope`; safe consent defaults). Known dup-identity limitation — D-062.
- **`payloads.py`** — pure Razorpay `payment.*` / `subscription.*` / `invoice.*`
  + synthetic `checkout.*` extractors. Subscription: `mandate_id` is
  **`payment.entity.token_id` only** (D-072), `mandate_type_from_method` (D-070,
  unknown → `NACH`). Checkout: `checkout_abandonment_context` (`cart_id` /
  `cart_value` paise→₹ / `drop_stage` / `payment_method_attempted` from the §4
  vocab, unknown → `NONE`). Invoice: `original`/`outstanding` (paise→₹,
  outstanding clamped to `[0, original]`), `due_date` (`expire_by`|`date`),
  `days_overdue`, `gst_inclusive`, `payment_terms`.
- **`outcomes.py`** — `BufferOutcome` enum (`NOOP` / `SELF_RECOVERED` /
  `CASE_CREATED` / `CASE_MERGED` (either direction) / `CASE_ATTACHED` (Leg-4
  bundle)) — shared by every ingestion path.
- **`checkout.py`** (Module-2 completion) — Leg 2. `create_checkout_case`: no
  buffer; idempotent on `source_event_id` + `event.processed`;
  `resolve_counterparty`; typed `CheckoutAbandonmentContext`;
  `find_supersedable_payment_case` → **reverse §2.4 Merge** (new abandonment
  case `superseded_by_case_id` → a pre-existing canonical `PAYMENT_DEGRADATION`
  case, context merged into the survivor, status unchanged — D-075/D-076);
  `sync_control_group`; `apply_active_hold_if_any` on a canonical case only;
  `Event.processed`.
- **`b2b.py`** (Module-2 completion) — Leg 4. `ingest_invoice`: no buffer;
  idempotent (`event.processed` + `source_event_id`); `resolve_counterparty`;
  the **locked §3 grouping rule** — open non-terminal `B2B_RECEIVABLE` case for
  `(merchant, counterparty)` → `B2BInvoice` attaches (`CASE_ATTACHED`), else new
  case (`context = {}`) + first invoice (`CASE_CREATED`); **no time window**;
  `case.amount_at_risk = Σ B2BInvoice.outstanding_amount`;
  `apply_active_hold_if_any` on create. D-077.
- **`subscription.py`** (M8) — Leg 3. `subscription_failure_buffer_seconds()`
  (30); `resolve_subscription_buffered_event` (NOOP / `_has_interim_charge`
  matched on `subscription.entity.id` → `SELF_RECOVERED` /
  `create_subscription_case`); `create_subscription_case` (idempotent on
  `source_event_id`; `resolve_counterparty`; insert
  `RevenueLeakCase(SUBSCRIPTION_FAILURE, DETECTED)` via `TenantScope` with a
  typed `SubscriptionFailureContext`; `sync_control_group`; `_seed_rail_budget`;
  `apply_active_hold_if_any`; `Event.processed`); `_seed_rail_budget` dispatches
  by `mandate_type` → `_seed_upi_retry_budget` (`attempts_used=1`) /
  `_seed_nach_retry_policy` (`clearing_cycle_status=RETURNED`,
  `dishonour_count_this_fy=1`) / `cases.seed_card_retry_budget` (reused). No
  cross-leg dedup. `cases._seed_card_retry_budget` → `cases.seed_card_retry_budget`
  (public, now shared).
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

Invariants: INV-24 (buffer → no case on self-recovery), INV-26 (every ingestion
case has a counterparty), **INV-27** (systemic detection idempotent), **INV-28**
(held case carries `systemic_event_id`), **INV-29** (resolution touches only its
own held cases), **INV-30** (Leg-3 self-recovery → no case), **INV-31** (Leg-3
case seeds exactly its rail's retry entity, once), **INV-32** (cross-leg Merge
symmetric + lossless, both directions — supersedes INV-25), **INV-33** (B2B
invoices bundle into one open case per merchant+counterparty), **INV-34** (every
ingestion entry point verifies before it parses/persists). All `HELPER`-class,
not `ORM-GUARD`.

**Not here:** `ISSUER_SPECIFIC` systemic detection (U-08); systemic rollup for
`subscription.charged.failed` (D-073); per-decline budget increments /
`mandate_cancelled_at` (Module 5); real NACH return code (Module 5); a real
storefront pixel (Part D item 1); token hashing; dispatch to Module 3 (D-080); a
`docker-compose` worker/beat service.

---

## 8C. Diagnosis Engine — `torque.diagnosis` — `IMPLEMENTED` (Module 3)

`diagnose_case(session, case_id=...)` converts a Module-2 canonical case into a
diagnosis and routes it. Package layout:

- **`root_causes.py`** — `RootCauseCode` (the Module-3-owned §3.1 vocabulary, a
  `StrEnum`; `.value` → the plain `String` column). `VALID_BY_LEG` (per-leg legal
  sets), `is_hard_decline_for` (derives the PAYMENT_DEGRADATION verdict from the
  code, D-084), `timing_hint_for` (§3.4 payday hint for the two NSF codes, D-079),
  `LABELS` (human `root_cause_label`).
- **`decline_codes.py`** — Razorpay decline-code → `DeclineCategory` + base
  confidence (known 0.75 / opaque 0.4, §3.2.2). A **demo-scope** seed table, same
  posture as the `MacCodeRegistry` seed (Decision M / Part E item 1).
- **`classifier.py`** — pure, DB-free per-leg rules → `DiagnosisResult`
  (`root_cause_code`, `diagnosis_confidence`, `reasoning`, `is_hard_decline?`,
  `suggested_timing_adjustment?`). Payment & subscription share the step 1–3 path
  (TIER_1/TIER_3 directive precedence 0.95 → decline lookup → missing-code
  fallback); subscription adds the §3.2.4 mandate **facts** first (1.0, D-082).
  Checkout classifies `(drop_stage, payment_method_attempted)` (every band < T);
  B2B buckets `days_overdue × promise_keeping_rate` (established 0.8 / cold-start
  0.4, D-084).
- **`engine.py`** — the orchestrator: `_is_eligible` gate (INV-35), tenant-scoped
  input gathering (rail budgets, invoices, `MerchantCounterparty`, source `Event`
  — INV-37), one `atomic()` block that transitions the case, writes the diagnosis
  fields (+ `context.is_hard_decline` for payment), appends the one
  `DIAGNOSIS_COMPLETED` event, and routes on `T` (INV-36/38). Returns
  `DiagnosisOutcome` (`NOOP` | `ROUTED_TO_PLAYBOOK` | `ESCALATED`).
- **`tasks.py`** — `diagnose_case_task` (Celery, registered via
  `celery_app.autodiscover_tasks([... , "torque.diagnosis"])` + explicit import).

**State machine:** uses the pre-existing `DETECTED → DIAGNOSING → {PLAYBOOK_ACTIVE
| ESCALATED_TO_HUMAN}` edges only — `state_machine.py` byte-unchanged. Handles
both the fresh `DETECTED` entry and the §2.5-resumed `DIAGNOSING` entry (skips the
`DETECTED` hop).

**Not here:** the Module 2 → Module 3 auto-dispatch trigger (D-080 — the engine +
task are ready, no leg enqueues them); the §5.3 first-touch MAC-code lookup at
diagnosis time (D-083, blocked on U-08 — Module 3 *consumes* an existing
`network_directive_tier` but extracts no MAC code); playbook selection /
instantiation (Module 4, now §8D); any retry/outreach/Temporal (Module 5). No new
`CaseEventType`, no state-machine edge, no `guards.py` change. *(Module 8 update:
`_apply_result` now also calls `torque.scoring.score_case(session, case)` inline
after routing — a derived-column refresh only, D-112 / §8H.)*

---

## 8D. Policy & Playbook Engine — `torque.policy` — `IMPLEMENTED` (Module 4)

Runtime layer over the `torque.playbooks` authoring contract. `activate_case(
session, case_id=...)` turns a diagnosed `PLAYBOOK_ACTIVE` case into a
version-pinned `PlaybookRun` (or an escalation). Package layout:

- **`catalog.py`** — the eleven §4.1 playbooks (slugs, `leg_type`/`mandate_type`
  discriminators, concrete `steps_graph` outreach/retry ladders, template
  `stopping_rules`). `seed_catalog(session)` inserts them **through the ORM** so
  the `before_flush` guard validates every graph + the UPI ≤3 ceiling (D-085,
  idempotent). Application-seeded, **not** a migration.
- **`selection.py`** — `select_playbook_id(leg_type, root_cause_code,
  mandate_type)`. Subscription `NSF_SOFT_DECLINE` is rail-specific;
  `INSTRUMENT_NOT_RECURRING_CAPABLE` maps per leg; the "trivial" §4.1 causes →
  `None`. Network-directive tier is *not* re-read (Module 3 folded it into the
  root cause).
- **`engine.py`** — `activate_case` / `ActivationOutcome` (NOOP / RUN_CREATED /
  ESCALATED_NO_PLAYBOOK / ESCALATED_DISABLED): eligibility (PLAYBOOK_ACTIVE,
  non-superseded, INV-41), one-live-run idempotency (INV-40, D-089), pin latest
  version (INV-39), `active_step_id = entry`, `status = RUNNING`, all in one
  `atomic()`; no-playbook / merchant-disabled → `PLAYBOOK_ACTIVE →
  ESCALATED_TO_HUMAN` (D-086). Run creation writes **no** CaseEvent (D-089).
  `resolve_effective_stopping_rules(session, run)` deep-merges the merchant
  override onto the run's **pinned** version's base (D-089).
- **`traversal.py`** — the pure "rules for reading" a graph: `entry_step_id`,
  `next_step_id(graph, step, outcome)`, `is_terminal`, `node`, `step_template`
  (§4.4 single vs `multi_case_template` + defer signal). No DB, no clock, no
  `active_step_id` mutation, no action execution — all Module 5.
- **`payday.py`** — the §4.3 policy gate: `payday_override_enabled(merchant)`
  (from `Merchant.risk_appetite_config`, default true, D-087) and
  `effective_timing_adjustment(case, merchant)`. The fire-time computation is
  Module 5 (D-025).
- **`tasks.py`** — `activate_case_task` (Celery), registered in `celery_app`.

**State machine:** uses only the pre-existing `PLAYBOOK_ACTIVE →
ESCALATED_TO_HUMAN` edge (no-playbook/disabled); run creation needs no transition
(case already `PLAYBOOK_ACTIVE`). `state_machine.py` byte-unchanged.

**Not here:** the Module 3 → Module 4 auto-dispatch trigger (D-088); the runtime
execution itself — all Module 5 (§8E).

---

## 8E. Execution & Orchestration — `torque.execution` — `IMPLEMENTED` (Module 5)

Executes a version-pinned `PlaybookRun`'s graph at runtime, driven by the §5.6
**Postgres-polling** driver (chosen over Temporal, D-090; resolves U-07). Package:

- **`scheduled_job` model + migration 0015** — the durable timer, one pending row
  per run (`UNIQUE(run_id)`, INV-43), `leg_type` denormalised for poller
  stratification. Tenant-scoped.
- **`scheduler.py`** — `schedule_run` (arm the entry timer, idempotent; applies the
  §4.3 payday substitution to the **entry** step only, D-094), `claim_due_jobs`
  (`fire_at <= now`, leg-filtered, `ORDER BY fire_at … FOR UPDATE SKIP LOCKED`),
  `execute_due_jobs` (one poll pass; runs **each job in its own `begin_nested()`
  SAVEPOINT**, D-095 — one poison job cannot roll back or stall siblings, returns
  `StepResult.ERROR`). Strata `PAYMENT_LEGS` (10 s) / `OTHER_LEGS` (60 s).
- **`runner.py`** — `execute_due_job`, the §5.1 tick (all-or-nothing per job): load
  the pinned run/graph (INV-44) → superseded-case guard (F-6) → stopping-rule check
  (`max_attempts`; `max_duration` measured from the **first executed action**, D-094
  → EXHAUSTED) → `allowed_hours` re-check (defer) → guardrails → execute →
  `write_action_and_event` (atomic Action+ActionCase+CaseEvent) → budget consumption
  → `STEP_TRANSITIONED` → advance `active_step_id` (Module 4's `traversal`, static
  offset, no re-payday) + reschedule, or finalize (ESCALATE_HUMAN terminal → case
  `ESCALATED_TO_HUMAN` / run `ESCALATED`; else case `EXHAUSTED` / run `COMPLETED` —
  D-096: `COMPLETED` ≠ recovered, the case status is the recovery signal).
  `StepResult` enum. Tenant-scoped throughout (INV-45).
- **`guardrails.py`** (§5.2, Module-5 half per D-092) — `check_retry_guardrails`
  (network hard-stop → rail budget → pre-debit gap w/ AUTO_INSERT self-heal →
  systemic hold) and `check_contact_guardrails` (systemic hold). `GuardKind`
  ALLOW/BLOCK/DEFER/AUTO_INSERT_PREDEBIT. UPI hard cap enforced (INV-46). Systemic
  hold is a §5.2 BLOCK following `on_blocked` — a transient outage drains an active
  run rather than pausing it (a blueprint gap; pause/resume needs the deferred
  `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` sweep — F-4, documented limitation).
- **`timing.py`** (D-025) — `compute_fire_time` (offset from previous completion,
  payday substitution `next_month_end_working_day` — entry step only, IST
  `allowed_hours` deferral incl. overnight), `within_allowed_hours`,
  `next_window_opening`, `next_upi_execution_time`. Inputs are timezone-aware; IST
  is a fixed offset (India has no DST).
- **`executor.py`** (§5.4) — `run_action` internal stub (no external I/O,
  monkeypatchable); `channel_for`. The seam real adapters attach to.
- **`rendering.py`** (§4.4) — `resolve_template` (single vs `multi_case_template`),
  `multi_case_context` (combined-amount context; rejects superseded cases); reuses
  `ActionCase` attribution (D-016), no second model.
- **`tasks.py`** — two Celery-beat pollers + beat schedule in `celery_app`.

**State machine:** uses the existing `PLAYBOOK_ACTIVE → {ESCALATED_TO_HUMAN,
EXHAUSTED}` edges only — `state_machine.py` / `guards.py` **byte-unchanged**.
**U-02 settled** (D-091): `STEP_TRANSITIONED` = `{run_id, from_step_id, outcome,
to_step_id?, edge_condition?}`.

**Module 6 wiring (added in Module 6, still in `torque.execution`):**
`runner._guardrails` now delegates to `GuardrailEngine.check()`; a
`DEFER`/`OUTREACH_COORDINATOR_DEFERRED` also writes an `ACTION_BLOCKED` row and
(open-conversation) enqueues, without advancing the step (D-099);
`runner._escalation_ceiling_hit` / `_escalate_on_ceiling` run one §6.3 check at
the top of the tick (D-100); `scheduler.execute_due_jobs` groups claimed outreach
jobs and folds 2+ via `coordination.merge` before the solo loop (D-102).
`StepResult` gains `ESCALATED_CEILING` and `MERGED`. `GuardDecision` gains
`defer_until` / `human_queue_reason`.

**Still deferred:** the Module 4 → 5 auto-dispatch trigger (D-093); real channel
adapters (§5.4); a real Temporal engine (D-090 — a driver swap); cross-stratum
merge (D-102 residual). *(Module 8 scoring is now `IMPLEMENTED` — §8H.)*

---

## 8F. Compliance & Cross-Leg Guardrail Engine — `torque.coordination` — `IMPLEMENTED` (Module 6)

The canonical home for the guardrail *decision* Module 5 consults (execution stays
Module 5's), plus escalation-ceiling handling and the human queue. Kept out of the
`torque.execution` package (Q-J); imported lazily by the runner to keep the graph
acyclic.

- **`guardrail_engine.py`** — `GuardrailEngine.check(session, *, action_type, now,
  case|case_id, run, node, params)` → `GuardDecision`. `RETRY_PAYMENT` delegates
  verbatim to `check_retry_guardrails` (unchanged §5.2 list 1). Contact actions run
  §5.2 list 2: systemic hold → cross-leg quiet period → WhatsApp gate #1/#2 →
  open-conversation → quiet-hours; first-failure-wins. `SEND_PRE_DEBIT_NOTIFICATION`
  gets systemic-hold only (parity with Module 5). `params` is pass-through — no
  params-validation subsystem (deferred). Returns the four-way `GuardDecision`
  (D-097).
- **`outreach_coordinator.py`** — pure helpers, all tenant-scoped:
  `priority(session, case)` (**the Module 8 seam** — delegates to
  `torque.scoring.compute_recovery_score(session, case).score`, D-098 / D-113;
  was the `amount_at_risk` placeholder taking only `case`);
  `cross_leg_quiet_period_defer(...)` (a customer-contact Action from a *different*
  leg for the same counterparty within `PolicyConfig.cross_leg_quiet_period_hours`
  (4h) → defer to `quiet_period_end + timing_offset`, pushed into `allowed_hours`);
  `open_conversation_defer(...)` (`Merchant_Counterparty.active_wa_conversation_expires_at
  > now` → defer past the window); `whatsapp_gate(...)` (gate #1
  `Counterparty.whatsapp_opt_in`, gate #2 `approved_template_exists` for an
  approved **UTILITY** template — reused, INV-21); `unsuccessful_action_count(...)`
  (the escalation-ceiling tally — `BLOCKED_BY_GUARDRAIL` / `FAILED` / `NO_RESPONSE`).
  `OUTREACH_ACTIONS` = `{SEND_WHATSAPP, SEND_EMAIL, SEND_SMS, GENERATE_PAYMENT_LINK}`.
- **`human_queue.py`** — `HumanQueueReason` (plain-string vocabulary:
  `LOW_CONFIDENCE_DIAGNOSIS`, `ESCALATION_CEILING`, `PROMISE_BROKEN`,
  `OPEN_WA_CONVERSATION`); `enqueue()` (idempotent on `case_id`);
  `list_for_merchant()` (priority desc + FIFO tie-break, or `order="fifo"`);
  `sweep_escalated_to_human()` (feeder 1 — origin-agnostic, no Module 3 change,
  Q-H); `route_broken_promise()` (feeder 3 — routing hook, never a harsher
  message).
- **`merge.py`** — `merge_groups()` + `execute_merged()`: the live Outreach
  Coordinator merge (Part A §5 / §4.4). Grouped from the poll batch (both jobs
  already claimed under one `SKIP LOCKED`); one merged `Action` attributed to the
  higher-`priority` run with one `ActionCase` per case (Σ `credit_weight` ==
  `Decimal("1.00000")` exact); with no `multi_case_template` the primary sends
  single-case and each secondary defers (`OUTREACH_COORDINATOR_DEFERRED`,
  timer bumped, step held). Cross-stratum residual race documented (D-102).

**New entity:** `human_queue` (`HumanQueueEntry`, `TenantScoped`, migration
**0016**) — `UNIQUE(case_id)`, `reason` (`String(32)`), `priority` (`Numeric(14,2)`),
`enqueued_at` (indexed). No enum, no new `CaseEventType`. *(Module 8: `priority`
now stores the recovery score at enqueue time; the daily sweep refreshes it in
place — D-113. Queue column shape unchanged.)*

**State machine:** the §6.3 escalation uses the existing legal
`PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN` edge — `state_machine.py` / `guards.py`
**byte-unchanged** (`git diff HEAD --` empty).

---

## 9. Attribution model — `IMPLEMENTED`

- `ActionCase(action_id, case_id, is_primary, credit_weight)` — universal (≥1 per
  Action). Σ `credit_weight` == 1.00000 exact, guard-enforced.
- **Module 7 (`IMPLEMENTED`, §8G):** `reconcile_event` writes
  `RevenueLeakCase.recovery_type` / `recovered_amount` inside `module7_writer`
  (INV-06, held open across every flush); direct `PaymentLink` →
  `AGENT_ASSISTED` / weight 1.0; indirect `(merchant, cp, amount)` match + 24h
  `Action` window → `AGENT_ASSISTED` else `SELF_RECOVERED`; a merged-outreach set
  re-splits the shared `Action`'s `ActionCase.credit_weight` ∝ `amount_at_risk`
  (INV-50/INV-12); a non-merged multi-match → `AMBIGUOUS`; no open match + a
  `DETECTED`/`DIAGNOSING` case → `CANCELLED` / `SELF_RECOVERED`.

---

## 8G. Reconciliation & Attribution — `torque.reconciliation` — `IMPLEMENTED` (Module 7)

Consumes verified success `Event`s from Module 2's pipeline (§7.3 — no webhook
path of its own; wired into `webhooks.py` dispatch, D-104).

- **`reconcile.py`** — `reconcile_event(session, *, event_id, now=None)` →
  `ReconcileOutcome` (`RECOVERED` / `PARTIALLY_RECOVERED` / `MULTI_RECOVERED` /
  `AMBIGUOUS_RECOVERED` / `SELF_PAID_CANCELLED` / `LINK_UPDATED` / `NO_MATCH` /
  `NOOP`). One transaction; idempotent on `Event.processed`; matched case rows
  `SELECT … FOR UPDATE`; tenant-scoped throughout. `RECONCILE_EVENT_TYPES` =
  `payment.captured` / `subscription.charged` / `payment_link.paid` /
  `.partially_paid` / `.expired` / `.cancelled`.
  - §7.1.1 direct — `payment_link.*` updates the `PaymentLink` row
    (`status` / `amount_paid` / `paid_at`); a `paid` / `partially_paid` for a
    Torque link → its `case_id`, `AGENT_ASSISTED`. Unknown link + a
    `notes.torque_case_id` → row created; without one → indirect.
  - §7.1.2 indirect — one open case (`PLAYBOOK_ACTIVE` / `ESCALATED_TO_HUMAN`, or
    B2B `PARTIALLY_RECOVERED`) matching `(merchant_id, counterparty_id, amount)`;
    `AGENT_ASSISTED` iff a non-blocked `Action` (any `ActionCase`) executed within
    `PolicyConfig.attribution_window_hours` (24h), else `SELF_RECOVERED` (D-105).
  - §7.1.3 merged — cases sharing one `Action`, or a set whose combined
    `amount_at_risk` a lump payment settles → re-split
    `ActionCase.credit_weight` ∝ `amount_at_risk`, recover all `AGENT_ASSISTED`.
    Non-merged multi-match → `AMBIGUOUS`, attribute to the latest-actioned case,
    leave the rest open (D-105).
  - §7.1.4 — no open match; a `DETECTED` / `DIAGNOSING` case for
    `(merchant, cp, amount)` → `CANCELLED` / `SELF_RECOVERED` (D-103).
  - §7.2 closure — full → `RECOVERED`, `recovered_amount = amount_at_risk`,
    `closed_at`; B2B partial → invoices waterfalled oldest-`due_date`-first,
    `PARTIALLY_RECOVERED` (open), `amount_at_risk` ← `Σ outstanding` (INV-33);
    a final B2B settlement two-hops `PARTIALLY_RECOVERED → PLAYBOOK_ACTIVE →
    RECOVERED` (D-106). Each close writes `PAYMENT_RECONCILED` and calls
    `human_queue.remove_for_case` (D-107).
- **`payloads.py`** — `payment_link.*` extractors. **`tasks.py`** —
  `reconcile_event_task`.
- **`state_machine.py`** — Module 7 added `DETECTED → CANCELLED` and
  `DIAGNOSING → CANCELLED` (D-103, the two U-01 edges; docstring updated).
  `guards.py` byte-unchanged.
- **New helpers:** `ingestion.identity.find_counterparty` (match-only),
  `coordination.human_queue.remove_for_case`. **No migration.**

---

## 8H. Recovery Scoring Model — `torque.scoring` — `IMPLEMENTED` (Module 8)

The single economic number `(probability × amount_at_risk) ÷ cost` for every open
case. The operative model is **benchmark probability → warm-start adjustment →
cost-aware score** — explainable, deterministic, no learned model (the XGBoost /
SHAP / uplift upgrade is 🔮 roadmap, §8.4 / Decision F).

- **`benchmarks.py`**
  - `cold_start_probability(leg_type, days_since_failure, *, amount_at_risk=None)`
    → the Decision F benchmark as an exact `Decimal`. Buckets:
    SUBSCRIPTION `hours ≤ 48` → 0.65 / `days ≤ 7` → 0.45 / else 0.25; PAYMENT
    DEGRADATION → 0.55; CHECKOUT → 0.40; B2B `days ≤ 30` → 0.35 / `≤ 90` → 0.20
    / else 0.12. `amount_at_risk` is accepted (Decision F names the dimension)
    but **inert** — no amount-tier variation is seeded (D-110).
  - `warm_start_multiplier(promise_keeping_rate | None)` — §8.2 linear map
    `cap_low + rate·(cap_high − cap_low)` = `0.5 + rate·0.8`, clamped
    `[0.5, 1.3]` (`PolicyConfig.warm_start_cap_low/high`). `None` (no history) →
    `1.0`. `adjusted_probability(base, rate)` = `clamp₀₁(base × multiplier)`,
    quantised 5 dp (D-110).
  - `bucket_label` / `amount_bucket` — display labels for the breakdown; the
    amount thresholds (SMALL <₹1k / MEDIUM ≤₹25k / LARGE) are a local grouping
    choice, no score effect.
- **`cost.py`** — `compute_cost(session, case) → CostBreakdown` (§8.2 / D-111).
  Next likely step = the node at a live `PlaybookRun.active_step_id` (`RUNNING`),
  else the candidate playbook's entry node (`select_playbook_id` +
  `entry_step_id`), else none. Channels via
  `execution.executor.channel_for`; Σ `ChannelRateCard.rate_per_unit`. Zero /
  unpriced (`payment_link`, missing row) / absent → `effective_cost` floors at
  `PolicyConfig.recovery_score_cost_floor` (₹0.01). `cost_basis` ∈ {`PRICED`,
  `FLOOR_NO_CHANNEL`, `FLOOR_UNPRICED_CHANNEL`, `FLOOR_NO_PLAYBOOK`};
  `next_step_source` ∈ {`LIVE_RUN`, `CANDIDATE_PLAYBOOK`, `NONE`}. No division by
  zero is structurally possible.
- **`score.py`**
  - `RecoveryScore` — frozen dataclass exposing every input so the calculation
    renders (§8.7): `score`, `probability`, `base_probability`,
    `warm_start_multiplier`, `promise_keeping_rate`, `amount_at_risk`,
    `raw_cost`, `effective_cost`, `cost_floor_applied`, `cost_basis`,
    `cost_channels`, `leg_type`, `amount_bucket`, `days_since_failure`,
    `bucket_label`, `next_step_action_type`, `next_step_source`, `computed_at`.
    `.explain()` → the "Why:" shape; `.to_dict()` → the JSONB breakdown.
  - `compute_recovery_score(session, case, *, now=None)` — **the one formula**,
    exact `Decimal`, quantised 4 dp. `days_since_failure` = live days overdue for
    B2B (`now − due_date` across the case's invoices, floored at the ingested
    `days_overdue`), else `now − opened_at`. `promise_keeping_rate` from the
    case-merchant's `Merchant_Counterparty` (tenant-scoped). A negative
    `amount_at_risk` → `RecoveryScoreError`; `None` → score 0.
  - `score_case(session, case, *, now=None)` — computes + writes
    `recovery_score` / `recovery_score_breakdown` / `recovery_score_updated_at`
    (no `CaseEvent`, no status change; no-op for a terminal case). Does not
    commit.
  - `recompute_open_cases(session, *, merchant_id=None, now=None)` — the §8.5
    daily sweep: re-score every open (`is_terminal` false) non-superseded case
    and refresh any `human_queue` entry's stored `priority`.
- **`tasks.py`** — `recompute_recovery_score_task(case_id)` and
  `recompute_open_case_scores_task()` on the existing Celery app.
- **Recompute wiring (§8.5 / D-112):** `score_case(...)` called inline at the end
  of `ingestion.{cases,checkout,subscription,b2b}` and
  `diagnosis.engine._apply_result`; one `beat_schedule` entry
  (`recovery-score-daily-recompute`, `crontab(hour=2, minute=0)`) +
  `torque.scoring` autodiscover in `ingestion.celery_app`.
- **Consumers:** `outreach_coordinator.priority(session, case)` returns
  `compute_recovery_score(...).score`; `human_queue` and `merge` route through
  that seam only — no consumer re-derives the formula (D-113).
- **New columns:** `revenue_leak_case.recovery_score` (`Numeric(18,4)`),
  `recovery_score_breakdown` (`JSONB`), `recovery_score_updated_at`
  (`TIMESTAMPTZ`) — migration **0017**, all nullable, no guard, no CHECK/FK
  (a derived cache, D-109). `PolicyConfig.recovery_score_cost_floor` (0.01) and
  `RecoveryScoreError` added.
- **State machine / guards:** **byte-unchanged** (Module 8 adds no transition and
  no guarded field).

---

## 8I. Reporting & Measurement — `torque.reporting` + `torque.api.reporting` — `IMPLEMENTED` (Module 9)

Turns the event stream + reconciliation outcomes into a business-level recovery
report. **Pure read/derive — no persisted aggregate, no migration** (D-114): a
reported number is always exactly what the live rows say, and is traceable
aggregate → case → actions → `CaseEvent` stream (§9.8).

- **`metrics.py`** — derivation functions, all tenant-scoped (`TenantScope` for
  tenant models; `case_event` has no `merchant_id`, so it is filtered by a join
  to `revenue_leak_case.merchant_id`, and the case is ownership-checked before
  its stream is returned):
  - `recovery_summary` (§9.2) — `case_count`, `revenue_at_risk` (D-115: non-B2B
    `amount_at_risk`; B2B `Σ B2BInvoice.original_amount`), `recovered_amount`
    (`recovery_type != SELF_RECOVERED` — D-116), `self_recovered_amount`
    (separate), `unresolved_amount` / `blocked_amount` / `deferred_amount`
    (D-118), `total_action_cost` (~0 until Module 5 populates `Action.cost`),
    the case-count buckets, `recovery_rate` (cases) + `amount_recovery_rate`
    (money) + `cost_efficiency_ratio` (D-117).
  - `recovery_by_leg` (§9.1 / §9.5) — the primary "by intervention" grouping;
    amount totals reconcile with the summary. `recovery_by_action_type` (§9.5
    secondary — overlapping rows, D-120). `recovery_by_recovery_type` (§9.2
    outcome). `recovery_over_time` (§9.2 — `date_trunc(bucket, closed_at)` UTC,
    Torque-credited `RECOVERED`, half-open windows — D-119).
  - `operational_exceptions` (§9.7) — `blocked_by_reason` (the §9.1 exception
    list), `deferred_action/case_count` (`OUTREACH_COORDINATOR_DEFERRED` only —
    pure timing defers write no `Action`), `failed_by_type`
    (`FAILED`/`NO_RESPONSE`), `escalated_case_count` + `escalations_by_reason`
    (`human_queue.reason`), `terminal_by_status`.
  - `recovery_report` (§9.4) — the batch bundle (`summary` + `by_leg` +
    `by_recovery_type` + `operational`) over one `opened_at` window.
  - `list_cases` / `case_detail` (§9.10) — drill-down; `case_detail` carries a
    per-action `ActionSummary` incl. this case's `ActionCase.credit_weight`
    (Module 7's split, surfaced not recomputed). `case_event_stream` (§9.2) —
    the raw `CaseEvent` stream in `event_seq_id` order (`reasoning` + `payload`).
  - `ReportWindow(start, end)` — half-open `[start, end)`; naive datetimes read
    as UTC. Applied to `opened_at` for batch membership, `closed_at` for the
    time series — separate query params so the two are never confused (D-119).
- **`schemas.py`** — frozen pydantic models; every money field a `Decimal`.
  `RecoverySummary`, `LegBreakdown`, `InterventionBreakdown`, `OutcomeBreakdown`,
  `TimeBucket`, `OperationalReport` (+ its row models), `CaseDetail` /
  `ActionSummary`, `CaseList` / `CaseListItem`, `CaseEventEntry`,
  `RecoveryReport`.
- **`torque.api.reporting`** — the 8 `GET` endpoints (§8A).
- **Attribution (§9.3):** Module 7 is authoritative — Module 9 reads
  `recovery_type` / `recovered_amount` / `credit_weight`, never re-matches a
  payment (INV-53).
- **Descriptive, not causal (§9.6):** incrementality lift, the Wilson score CI,
  and SUTVA-adjusted lift (Blueprint §9.1) are **`DEFERRED`** (D-121 / U-10 —
  "Module 9b — Incrementality"). The `in_control_cohort` / `control_group` data
  is collected and untouched.
- **State machine / guards / migrations:** **none.** `alembic head` stays
  `0017_recovery_score`; `git diff HEAD --` of `state_machine.py` and
  `guards.py` empty.
- **Module 10 extension:** the router also serves `GET /reports/{m}/top-at-risk`
  (`top_at_risk_cases` — open cases `ORDER BY recovery_score DESC NULLS LAST`),
  `/human-queue` (`human_queue_list` — `human_queue` rows joined to the case,
  ordered by the entry's stored `priority`), `/activity` (`recent_activity` —
  recent `CaseEvent`s, newest `event_seq_id` first). `case_detail` returns
  `recovery_score_breakdown` (Module 8's §8.7 dict, verbatim),
  `recovery_probability`, `counterparty_label`, `root_cause_code`, and the
  `escalation_*` fields. Still GET-only, still `TenantScope`d (INV-58).

---

## 8J. UI/UX — `torque.ui` + `torque.agent_console` + `torque.demo` — `IMPLEMENTED` (Module 10)

Makes Torque a runnable, demo-able product. `uv run python -m torque` serves the
JSON API **and** a static dashboard on one port (`http://127.0.0.1:8000/ui/`).

- **`src/torque/ui/static/`** — `index.html` + `torque.css` + `torque.js`
  (vanilla, no framework, no bundler — D-122). Mounted with `StaticFiles` at
  `/ui` by `api.ui.mount_ui`. Hash-router SPA (`#/dashboard`, `#/cases/<id>`,
  `#/console`, `#/demo`); holds a `merchant_id` in client state and calls only
  tenant-scoped backend paths; computes **no** metric / score / ranking
  (all from the API). Live feed = polling `/reports/{m}/activity` every 3 s.
- **`torque.agent_console`** (`resolve.py`) — `resolve_escalation` /
  `pause_case` / `unpause_case` (INV-59). `resolve_escalation`:
  `ESCALATED_TO_HUMAN → {RECOVERED | PARTIALLY_RECOVERED | WRITTEN_OFF}` via
  `transition_case` (edges already legal), sets `escalation_resolution` /
  `_by` / `_at`, writes a `HUMAN_RESOLVED` `CaseEvent` (`actor=HUMAN`), and for a
  recovering resolution sets `recovered_amount` + `recovery_type = AGENT_ASSISTED`
  inside `guards.human_resolution_writer`; removes the case from the human queue.
  `EscalationResolution` StrEnum owned here (not a PG enum). "Cancel" (§10.8) =
  resolve → `WRITTEN_OFF` (D-124). `pause`/`unpause` = `PLAYBOOK_ACTIVE ↔ PAUSED`.
- **`torque.demo`** — `seed.py` (`seed_demo(session, *, now=DEMO_NOW,
  reset=False)` — a fixed 16-case `acc_demo` dataset across all 4 legs and every
  archetype: recovered / self-paid / B2B-partial / blocked / deferred /
  escalated / exhausted / open, each with a `CaseEvent` trail, all Module-8
  scored; idempotent, `reset` disables the `case_event` trigger for the wipe —
  D-125) + `scenarios.py` (`inject_scenario(session, key)` — composes the real
  `create_or_attach_case` / `create_checkout_case` / `create_subscription_case`
  ingestion + seeds the blocking budget row + asserts the real compliance
  predicate refuses, for `hard_stop_mac` / `upi_retry_cap` / `nach_ceiling`; no
  parallel event mechanism).
- **`revenue_leak_case`** gains `escalation_resolution` / `escalation_resolved_by`
  / `escalation_resolved_at` (`VARCHAR(64)` / `VARCHAR(64)` / `TIMESTAMPTZ`,
  nullable) — migration **0018**. Unguarded columns.
- **`guards.py`** gains `human_resolution_writer(session)` + the `hr` flag in
  `_guard_case` (D-123). **`state_machine.py` byte-unchanged.**

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
- **`IMPLEMENTED` (Module 6, §8F):** `GuardrailEngine.check()` (the facade),
  quiet-hours defer on contact, the Outreach Coordinator (`priority()` seam, 4h
  cross-leg quiet period, live merge, defer, open-conversation), escalation-ceiling
  → `ESCALATED_TO_HUMAN`, and the persistent `human_queue`.
- **`IMPLEMENTED` (Module 8, §8H):** the real `(probability × amount) ÷ cost`
  recovery score now flows through the `priority()` seam into both the merge
  primary-selection and the human-queue ordering.
- **`PLANNED` / `DEFERRED`**: a per-node WhatsApp template category (the gate
  checks UTILITY).

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
                     ingestion/{buffer,subscription,b2b,tasks} (enqueue)        # M7a…Module 2
api/checkout_injection.py  <-  api/deps, config, db/scoped, security/razorpay_signature,
                     ingestion/{checkout,tasks}, models (Event, Merchant)       # Module 2 completion
api/app.py  <-  api/{webhooks,checkout_injection} ;  __main__.py  <-  api/app.py (uvicorn factory)
ingestion/celery_app.py  <-  config.py (redis_url) ; beat_schedule -> detect_systemic  # M7b + M7c
ingestion/tasks.py  <-  celery_app, db/session ; -> ingestion/{buffer,subscription,checkout,b2b,systemic}
ingestion/buffer.py  <-  ingestion/cases, ingestion/payloads, ingestion/outcomes, config (policy)
ingestion/cases.py  <-  ingestion/{payloads,identity,dedup,outcomes,systemic}, db/scoped,
                        state_machine (sync_control_group), models (Event, RevenueLeakCase, CardRetryBudget)
ingestion/subscription.py  <-  ingestion/{payloads,identity,outcomes,systemic}, ingestion/cases  # M8
                        (seed_card_retry_budget), db/scoped, state_machine, models (…, UPIRetryBudget, NACHRetryPolicy)
ingestion/checkout.py  <-  ingestion/{payloads,identity,outcomes,systemic,dedup}, db/scoped,   # Module 2 completion
                        state_machine (sync_control_group), models (Event, RevenueLeakCase)
ingestion/b2b.py  <-  ingestion/{payloads,identity,outcomes,systemic}, db/scoped,               # Module 2 completion
                        state_machine (is_terminal, sync_control_group), models (Event, RevenueLeakCase, B2BInvoice)
ingestion/dedup.py  <-  state_machine (is_terminal), config (policy), ingestion/payloads, models (Event, RevenueLeakCase)
ingestion/systemic.py  <-  compliance/systemic (predicates), state_machine (transition_case),   # M7c
                        events (append_case_event), db/scoped, config (policy),
                        models (Event, RevenueLeakCase, SystemicEvent)
```
(`state_machine.py` is imported FROM by `ingestion/{cases,dedup,systemic,subscription,checkout,b2b}`
— read-only. `state_machine.py` was byte-stable M1→M7b; **M7c added exactly one
edge** `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` + a docstring cleanup — D-066. M8 and
the Module-2 completion run touched neither `state_machine.py` nor `guards.py`.)

Circular-import care points (already handled in code, do not "fix"):
- `models/guards.py` imports `Action` / `ActionCase` / `PromiseToPay` **lazily
  inside** `_before_flush` (models `__init__` imports `action` first, and
  `db.session` pulls in `guards` mid-import).
- `contexts/registry.py` imports the concrete context models at the **bottom** of
  the file.
- `state_machine.py` imports several names **from** `models/guards.py`.

---

## 14. What is explicitly NOT here

See `DEFERRED.md` for the full register. Highlights: the HTTP routes are
`GET /health`, `POST /webhooks/razorpay/{merchant_id}`, and
`POST /internal/checkout-abandoned/{merchant_id}` — no other endpoint, no auth
layer. **Celery + Redis** (broker only) + **Celery beat** run the four inbound
ingestion tasks and the M7c §2.5 job — but no Temporal, no `PlaybookRun`
workflow engine, no Postgres-polling job table (U-07 remaining half), no
`docker-compose` worker/beat service. Module 2 is complete for all four legs;
what remains is **not Module 2's job**: no `ISSUER_SPECIFIC` systemic detection
(U-08), no systemic rollup over `subscription.charged.failed` (D-073), no
per-decline budget increments / `mandate_cancelled_at` (Module 5), no real NACH
return code (Module 5), no real storefront pixel (Part D item 1), no card-token
hashing, no code that drives `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` (edge legal but
dormant). **Module 3 diagnosis is now `IMPLEMENTED`** (§8C) — but with no
automatic `Event`→Diagnosis dispatch from ingestion (D-080; the engine + task are
ready, nothing enqueues them) and no §5.3 first-touch MAC-code lookup at diagnosis
time (D-083, blocked on U-08). **Module 4 policy & playbook engine is now
`IMPLEMENTED`** (§8D) — the §4.1 catalog, selection, and version-pinned
`PlaybookRun` instantiation — but with no automatic Diagnosis→Activation dispatch
(D-088). **Module 5 execution & orchestration is now `IMPLEMENTED`** (§8E) — the
§5.6 Postgres-polling driver (chosen over Temporal, D-090; resolves U-07), runtime
graph traversal advancing `active_step_id`, timing/payday/`allowed_hours` (D-025),
the §5.2 retry/systemic guardrails + Card/UPI/NACH consumption, and the atomic
Action+CaseEvent write — but with no automatic Module 4→5 dispatch (D-093) and
**no real channel adapters** (`executor.run_action` is a stub, §5.4).
**Module 6 compliance & cross-leg guardrail engine is now `IMPLEMENTED`** (§8F) —
the `GuardrailEngine` facade, the Outreach Coordinator, the WhatsApp gate,
escalation-ceiling escalation, the persistent `human_queue` (migration 0016).
**Module 7 reconciliation & attribution is now `IMPLEMENTED`** (§8G) — payment →
case matching, `AGENT_ASSISTED` vs `SELF_RECOVERED`, case closure, the two U-01
`→ CANCELLED` edges. **Module 8 recovery scoring is now `IMPLEMENTED`** (§8H) —
`(probability × amount_at_risk) ÷ cost` persisted on `revenue_leak_case`
(migration 0017), recomputed on creation / diagnosis / daily, driving the
`priority()` seam. **Module 9 reporting & measurement is now `IMPLEMENTED`**
(§8I) — the read-only `torque.reporting` derivations + `/reports/{merchant_id}/…`
API (outcome-based recovery report, by leg / intervention / outcome / time, the
operational exception report, case drill-down + the `CaseEvent` explainability
stream), no migration. **Module 10 UI/UX is now `IMPLEMENTED`** (§8J) — a static
SPA dashboard served by the same process (`/ui`), the Agent Console
(`torque.agent_console` — human resolve/pause, `escalation_resolution` +
`HUMAN_RESOLVED`, migration **0018**, `guards.human_resolution_writer`), and the
Demo Surface (`torque.demo` — deterministic `acc_demo` seed + one-click
Decision-K scenarios + a polling live feed). Still absent: **incrementality /
causal measurement** ("Module 9b" — lift + Wilson CI + SUTVA, D-121), Module 11
infra consolidation, the `MacCodeRegistry` full seed, real channel adapters,
`Action.cost` population, a real Temporal engine, and code that drives
`PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` (edge legal but dormant).
