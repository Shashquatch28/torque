# DEFERRED WORK REGISTER

Work that is **deliberately not built yet**. If you are about to implement
something here, STOP — it belongs to a future milestone and must be an explicit,
approved proposal first. Presence in this list is not a bug or an oversight; it
is a scoping decision.

Remove an item **only** when it is actually implemented (and record that in
`MILESTONES.md`). Organized by owning module.

Legend: 🔧 build (planned) · 📋 design-only for demo · 🔮 roadmap / out of demo scope.

---

## Module 2 — Signal Ingestion

- ✅ **DONE in M7a:** the FastAPI application (`torque.api`), the Razorpay webhook
  HTTP endpoint `POST /webhooks/razorpay/{merchant_id}` + `GET /health`, the
  verify-before-parse pipeline, and the `Event` write path with the
  `X-Razorpay-Event-Id` idempotency check. See `MILESTONES.md` Milestone 7a.
- ✅ **DONE in M7b (Leg 1 only):** **Celery + Redis** delayed-job wiring
  (`torque.ingestion.celery_app`, broker only — resolves the inbound half of
  Decision C / U-07; Celery stands in for Node-only "BullMQ" — D-057); the
  **self-recovery buffer** for `payment.failed` (90s, §2.3); **cross-leg dedup /
  merge** live direction (`payment.failed` after an open `CHECKOUT_ABANDONMENT`
  case — `superseded_by_case_id` + context carried into the survivor, §2.4);
  the **first `RevenueLeakCase` creation path** (`payment.failed` →
  `PAYMENT_DEGRADATION` in `DETECTED`, counterparty resolution,
  `Merchant_Counterparty`); **`CardRetryBudget` seeding** to 1 for card
  `payment.failed` (§2.7). See `MILESTONES.md` Milestone 7b.
- 🔧 **Self-recovery buffer — `subscription.charged.failed` half** (30s;
  `PolicyConfig.subscription_failure_buffer_seconds` exists). Needs Leg-3
  ingestion.
- 🔧 **Cross-leg dedup — reverse direction** (`checkout.abandoned` arriving after
  a `PAYMENT_DEGRADATION` case). Deferred with **Leg-2 ingestion** — there is no
  `checkout.abandoned` producer until then (D-060).
- ✅ **DONE in M7c (`NETWORK_WIDE` tier only):** the 60s Celery-beat systemic
  detection job (`torque.ingestion.systemic`) — per-merchant trailing-10-min
  failures/min vs. a trailing-7-day baseline that excludes the live window,
  compound threshold via `systemic_threshold_breached`, `SystemicEvent(NETWORK_WIDE)`
  creation, sweep of open `DETECTED` cases → `SYSTEMIC_HOLD` (+ `STATUS_CHANGED`
  + `SYSTEMIC_HOLD_APPLIED`), resolution via `systemic_resolved` → `resolved_at`
  + batch `SYSTEMIC_HOLD → DIAGNOSING` (FK left set), and the §2.7 ingestion hook.
  See `MILESTONES.md` Milestone 7c. **Still open below.**
- 🔧 **`ISSUER_SPECIFIC` systemic detection** — blocked: no issuer / BIN /
  acquirer / route value is extracted from any payload or stored on `Event`, any
  leg context, or `RevenueLeakCase` (`Network` is `MASTERCARD|VISA` only). See
  `UNRESOLVED.md` **U-08**. Do NOT parse arbitrary Razorpay JSON to manufacture
  it; do NOT add issuer columns.
- 🔧 **Systemic detection tuning** — N (`systemic_baseline_floor_per_min`) and M
  (`systemic_absolute_count_floor`) remain **U-04 placeholders**. M7c consumes
  them as configured; it does not empirically validate or retune them.
- 🔧 **`UPIRetryBudget` counter seeding** + **per-decline retry-budget increment
  semantics** (M7b seeds `CardRetryBudget` to 1 and no-ops if the row exists;
  incrementing on each decline / each `RETRY_PAYMENT` is Module 5). UPI seeding
  is a **Leg-3 definition-of-done requirement** — mandate-scoped, from the
  `subscription.charged.failed` (`mandate_type = UPI_AUTOPAY`) producer + its
  `SubscriptionFailureContext` (D-069). M7c implements none of it.
- 🔧 **Instrument-key hardening (keyed-HMAC / pepper)** — M7b stores the Razorpay
  tokenised card reference `COALESCE(token_id, card_id)` in the inherited
  `CardRetryBudget.card_token_hash` column (no PAN received or stored; column not
  renamed; no hashing performed — D-061). A keyed-HMAC/pepper representation of
  the instrument key is a future security-hardening item, not started.
- 🔧 **Leg 3 ingestion** — `subscription.charged.failed` → `SUBSCRIPTION_FAILURE`
  case (all four `SubscriptionFailureContext` fields, Razorpay method →
  `mandate_type` mapping, 30s buffer).
- 🔧 **`B2BInvoice` bundling trigger** (Leg 4) — on `invoice.overdue`, attach to
  an open non-terminal B2B case for the same `(merchant_id, counterparty_id)` or
  open a new one (§3 locked grouping logic).
- 📋 **Checkout-abandonment ingestion mechanism** (Leg 2) — no Razorpay webhook
  exists; proposed default is synthetic injection via a signed internal endpoint
  (Part D item 1). A real storefront SDK/pixel with its own HMAC scheme is 🔮.
- ✅ **DONE in M7c:** `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` added to
  `state_machine.py` (U-01 #3, D-066) as a **legal but dormant** edge. **Driving
  it** (a sweep that includes active playbook runs) + mid-run recovery semantics
  is Module 5 — M7c produces no `PLAYBOOK_ACTIVE` case.
- 🔧 **Dispatch to Module 3** — an ingestion-created case is left in `DETECTED`
  (or `DIAGNOSING` after systemic resolution); nothing hands it to Diagnosis yet.
- 🔧 **A `docker-compose` Celery worker/beat service** — M7b/M7c ship the dev
  commands (`... worker`, `... beat`) and eager-mode tests only.

## Module 3 — Diagnosis Engine

- 🔧 The **`root_cause_code` enum** (Module 3 owns it — deliberately NOT in
  `enums.py`; `RevenueLeakCase.root_cause_code` is a plain `String`).
- 🔧 Per-leg rule-based classification, confidence bands, decline-code lookup
  table, mandate-type overrides.
- 🔧 `DIAGNOSING → PLAYBOOK_ACTIVE` vs `DIAGNOSING → ESCALATED_TO_HUMAN` routing
  on `PolicyConfig.diagnosis_confidence_threshold` (0.65).
- 🔧 `suggested_timing_adjustment` (payday-cycle heuristic) emission.
- 🔧 Writing `DIAGNOSIS_COMPLETED` `CaseEvent`s.

## Module 4 — Policy & Playbook Engine (runtime)

- 🔧 The **playbook catalog** — concrete `Playbook` rows per `root_cause_code`
  (`PLAYBOOK_NSF_RETRY`, `PLAYBOOK_REQUEST_NEW_INSTRUMENT`, …). None are seeded.
- 🔧 **`PlaybookRun` instantiation** — selecting a playbook, creating the run,
  version pinning at runtime.
- 🔧 `active_step_id` advancement / graph traversal.
- 🔧 `step_timing_semantics` execution (offset from previous step's completion;
  defer to next `allowed_hours` window; never fire early/skip).
- 🔧 `payday_cycle_override_enabled` runtime substitution.
- 🔧 `multi_case_template` / `multi_case_context` rendering.
- 🔧 Action-specific `params` schemas (deferred from M4's graph validation).

## Module 5 — Execution / Orchestration

- 🔧 **Temporal** workflow-per-`PlaybookRun` (or the Postgres-polling fallback:
  `scheduled_jobs` table + stratified 10s/60s pollers). Go/no-go open (Part E
  item 8).
- 🔧 **`checkGuardrails` / `executeAction` / `writeActionAndEvent` /
  `waitForNextStep`** activities. Only the *write primitive*
  (`write_action_and_event`) exists.
- 🔧 The **guardrail check sequence** (§5.2 ordered, first-failure-wins) for
  `RETRY_PAYMENT` and for customer-contact actions.
- 🔧 **Channel adapters:** Meta WhatsApp Cloud API, Resend email, Fast2SMS,
  Razorpay Payment Links create, Razorpay retry / Mandate Execute / NACH
  re-presentment. None exist.
- 🔧 **`GENERATE_PAYMENT_LINK` execution** — creating a `PaymentLink` row from a
  real Razorpay `plink_...`.
- 🔧 **`LOG_PROMISE` execution** — creating a `PromiseToPay` from a captured
  promise + writing `PROMISE_CAPTURED`.
- 🔧 **`write_action_and_event` extension** for real channel/cost values (M5 left
  `channel`/`cost` nullable — D-031).
- 🔧 **`MacCodeRegistry` self-healing**: on an unseeded code, default to
  `TIER_2_CAPPED_RETRY` and write a flagged `CaseEvent`. `tier_for()` currently
  just returns `None`.
- 🔧 **Retry-rail enforcement** — actually blocking a `RETRY_PAYMENT` on
  `card_retry_within_budget` / `upi_attempt_gate_open` /
  `within_upi_execution_window` / `nach_retry_eligible`. Predicates exist;
  nothing calls them to block.
- 🔧 **Pre-debit self-heal** — auto-inserting a `SEND_PRE_DEBIT_NOTIFICATION`
  step ahead of a retry when `gap_satisfied` is false.
- 🔧 Cost computation from `ChannelRateCard`.

## Module 6 — Compliance & Cross-Leg Guardrail Engine

- 🔧 **`GuardrailEngine.check(action_type, case_id, params)`** — the single
  callable interface. Does not exist.
- 🔧 The full **`SEND_WHATSAPP` guardrail**: gate #1 (`Counterparty.whatsapp_opt_in`)
  AND gate #2 (`approved_template_exists`) AND the open-conversation check
  (`Merchant_Counterparty.active_wa_conversation_expires_at > now()` → suspend
  templates, route to human), producing `Action.outcome = BLOCKED_BY_GUARDRAIL`
  with `CONSENT_NOT_OBTAINED` / `TEMPLATE_NOT_APPROVED`. Only the gate-#2
  predicate exists.
- 🔧 **Quiet-hours** enforcement (defer, not block) on customer contact.
- 🔧 **Outreach Coordinator** (Part A §5, owned by Module 6): the
  `(probability × amount) ÷ cost` priority, the 4h cross-leg minimum quiet
  period, merge policy (one `Action` with multi-`ActionCase`), defer policy
  (`OUTREACH_COORDINATOR_DEFERRED` `CaseEvent`), open-conversation policy.
- 🔧 **Escalation-ceiling** handling — Module 6 (not Module 5) transitions a run's
  case to `ESCALATED_TO_HUMAN` at `stopping_rules.escalation_ceiling`.
- 🔧 **Human queue** — FIFO-per-merchant keyed on `case_id`, fed by
  low-confidence diagnoses + escalation-ceiling + `PromiseToPay` broken, sorted
  by the Module 8 score.
- 🔧 Human-agent routing for `PromiseToPay` `BROKEN` (deliberately not a per-row
  column — D-038).

## Module 7 — Payment Reconciliation & Attribution

- 🔧 Matching `payment.captured` / `subscription.charged` / `payment_link.paid` to
  open cases: direct `PaymentLink` match → `AGENT_ASSISTED`, `credit_weight=1.0`;
  indirect `(merchant, counterparty, amount)` match + 24h action window
  (`PolicyConfig.attribution_window_hours`); multi-case proportional split;
  no-match → `CANCELLED` / `SELF_RECOVERED`.
- 🔧 Writing `RevenueLeakCase.recovery_type` / `recovered_amount` via
  `guards.module7_writer(session)` (the context manager exists; no caller).
- 🔧 `credit_weight` re-splitting on `ActionCase` at reconciliation.
- 🔧 Case closure (`RECOVERED` / `PARTIALLY_RECOVERED`, `B2BInvoice.outstanding_amount`
  decrement) + `PAYMENT_RECONCILED` `CaseEvent`.
- 🔧 State-machine edges `DETECTED → CANCELLED`, `DIAGNOSING → CANCELLED` (not in
  `state_machine.py` — `UNRESOLVED.md` #1).
- 🔧 Webhook-driven `PaymentLink.status` / `amount_paid` / `paid_at` transitions.

## Module 8 — Recovery Scoring Model

- 🔧 `probability = lookup(leg_type, amount_bucket, days_since_failure)` as a live
  function (Decision F benchmark table).
- 🔧 Warm-start adjustment by `promise_keeping_rate`, capped
  0.5×–1.3× (`PolicyConfig.warm_start_cap_low/high`; the 0.5/1.3 defaults are
  unverified — Part E item 12).
- 🔧 Cost sourcing (next-likely-step channel sum from `ChannelRateCard`).
- 🔧 Recompute cadence (creation / diagnosis / daily).
- 🔮 XGBoost + SHAP + T/X-learner upgrade (needs 500+ resolved cases).

## Module 9 — Reporting & Measurement

- 🔧 Dashboard metrics (₹ recovered by leg, recovery rate, incrementality lift +
  Wilson CI, SUTVA-adjusted lift, exception list, cost efficiency).
- 🔧 Explainability panel (mechanical render of the `CaseEvent` stream).
- 🔧 Cross-merchant SUTVA footnote logic.

## Modules 10–13

- 🔧 All UI (merchant dashboard, agent console, demo surface + synthetic-event
  injector).
- 🔧 Infra beyond `docker-compose` (Temporal cluster or fallback, prod queue).
- 🔧 Build roadmap calendar dates (Part D item 3).
- 🔧 Demo script finalization (Part D item 4 — judging rubric).

## Cross-cutting / schema-adjacent deferrals

- 📋 **DPDP erasure-request intake** UI/endpoint (Decision H / Part E item 7).
  The schema supports erasure (`redact_pii`); the request flow is not built.
- 🔧 **`Action.content_sent` redaction cascade** on erasure (column exists,
  orchestration deferred).
- 🔧 **`MacCodeRegistry`** unseeded codes + full Visa equivalent set (Part E
  item 1 / Decision M) — a Module 5 pre-production checklist item, self-surfacing
  via flagged `CaseEvent`s once Module 5 exists.
- 🔧 **`whatsapp_template_category` `AUTHENTICATION` value** — add via explicit
  `ALTER TYPE ... ADD VALUE` only if an auth-template use case appears (D-041).
- 🔧 **Meta/WABA template + status sync** — pulling `MerchantWhatsAppTemplate`
  rows and `approval_status` from Meta; template **version / history / quality
  rating** tracking (none modelled — the table is a flat current-state snapshot).
- 🔧 **Systemic threshold placeholders** — `PolicyConfig.systemic_baseline_floor_per_min`,
  `systemic_absolute_count_floor`, `systemic_sustain_window_minutes` carry
  invented defaults (no blueprint figure); tune when Module 2 §2.5 is built
  (D-048).
- 🔮 **NACH cross-instrument aggregation** (cheque + NACH dishonours) — needs
  bank-side visibility (Part E item 4).
- 🔮 **SMS production path** — TRAI DLT registration (Part E item 5).
- 🔮 **Card Account Updater (CAU)** — no free tier; excluded entirely (Part E
  item 6).
- 🔮 **Postgres Row-Level Security** — defense-in-depth beyond `TenantScope`
  (blueprint §2.1).
- 🔧 **`PlaybookRun.status`** runtime transitions (enum + default only today).
