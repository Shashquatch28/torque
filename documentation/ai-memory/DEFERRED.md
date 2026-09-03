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
- ✅ **DONE in M8 (Leg 3):** the **30 s self-recovery buffer** for
  `subscription.charged.failed` (`torque.ingestion.subscription`, §2.3); the
  **`SUBSCRIPTION_FAILURE` case creation path** (typed `SubscriptionFailureContext`
  — `mandate_id` / `mandate_type` (D-070 method map) / `billing_cycle` /
  `subscription_id`; counterparty + `Merchant_Counterparty` resolution;
  `DETECTED`); **rail-specific retry-budget seeding** in the case transaction
  (D-072) — `UPI_AUTOPAY → UPIRetryBudget(attempts_used=1)`,
  `NACH → NACHRetryPolicy(RETURNED, dishonour_count=1)`,
  `CARD → CardRetryBudget` (reused seeder). The M7c systemic hold hook applies.
  See `MILESTONES.md` Milestone 8. **Residuals below.**
- ✅ **DONE in the Module 2 completion run (Legs 2 & 4 + bidirectional Merge):**
  the §2.6 **signed synthetic `checkout.abandoned` injection endpoint**
  (`POST /internal/checkout-abandoned/{merchant_id}`, `torque.api.checkout_injection`,
  dedicated `Settings.checkout_injection_secret`, D-074); **Leg 2
  `CHECKOUT_ABANDONMENT` case creation** (`torque.ingestion.checkout`, typed
  `CheckoutAbandonmentContext`, no buffer); the **reverse §2.4 cross-leg Merge**
  (`checkout.abandoned` after an open `PAYMENT_DEGRADATION` case — symmetric with
  the forward direction; abandonment superseded into the canonical payment case;
  no new `CaseEventType`, D-075/D-076); **Leg 4 `invoice.overdue` ingestion**
  (`torque.ingestion.b2b`, `B2BInvoice` + the locked §3 grouping rule, no buffer,
  `case.amount_at_risk` = Σ outstanding, D-077); the §2.7 systemic hold hook on
  canonical Leg-2 / Leg-4 cases (D-078). **Module 2 is now complete.** See
  `MILESTONES.md` "Module 2 — Signal Ingestion — COMPLETE".
- 🔧 **Systemic detection rollup does not count `subscription.charged.failed`** —
  M7c/M8's `NETWORK_WIDE` rate counts only `Event(type="payment.failed")`
  (D-073). Extending it to subscription failures is a future refinement (the
  blueprint §2.5 does not enumerate which event types feed the rate).
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
- 🔧 **Per-decline retry-budget increment semantics** (all rails seed to 1 and
  no-op if the row exists; incrementing on each decline / each `RETRY_PAYMENT`,
  plus `UPIRetryBudget.mandate_cancelled_at` on the 4th attempt, is Module 5).
- 🔧 **Real NPCI NACH `return_reason_code` + `retry_eligible_after`** — M8 seeds
  `NACHRetryPolicy` with `return_reason_code = None` / `retry_eligible_after =
  None`; the real return code arrives via the bank return file and the next
  batch-clearing date is computed by Module 5 (D-072).
- 🔧 **Instrument-key hardening (keyed-HMAC / pepper)** — M7b stores the Razorpay
  tokenised card reference `COALESCE(token_id, card_id)` in the inherited
  `CardRetryBudget.card_token_hash` column (no PAN received or stored; column not
  renamed; no hashing performed — D-061). A keyed-HMAC/pepper representation of
  the instrument key is a future security-hardening item, not started.
- 🔮 **Real storefront SDK/pixel for Leg 2** — the Module 2 completion run built
  the demo-scope **signed synthetic injection** endpoint (Part D item 1's
  confirmed default). A real per-merchant storefront integration with its own
  HMAC scheme is a separate future build item.
- 🔧 **`B2BInvoice` partial-payment / `outstanding_amount` decrement, dunning,
  case closure** — Leg-4 ingestion (done) creates the invoice + case and
  maintains `amount_at_risk` = Σ outstanding; decrementing `outstanding_amount`
  on payment and closing the case are Modules 4–7.
- ✅ **DONE in M7c:** `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` added to
  `state_machine.py` (U-01 #3, D-066) as a **legal but dormant** edge. **Driving
  it** (a sweep that includes active playbook runs) + mid-run recovery semantics
  is Module 5 — M7c produces no `PLAYBOOK_ACTIVE` case.
- 🔧 **Dispatch to Module 3 (the auto-trigger)** — the Module 3 engine + task
  exist and are invocable, but no ingestion leg enqueues `diagnose_case_task`; an
  ingestion-created case is left in `DETECTED` (or `DIAGNOSING` after systemic
  resolution) for a separate orchestration step to pick up (D-080, moved here from
  "Dispatch to Module 3"). Wiring the enqueue is an orchestration-layer concern.
- 🔧 **A `docker-compose` Celery worker/beat service** — M7b/M7c ship the dev
  commands (`... worker`, `... beat`) and eager-mode tests only.

## Module 3 — Diagnosis Engine — ✅ COMPLETE

Built in the Module 3 run (`torque.diagnosis`). The following are now **DONE**:
- ✅ The **`root_cause_code` vocabulary** — `RootCauseCode` in
  `torque.diagnosis.root_causes` (Module 3 owns it; `RevenueLeakCase.root_cause_code`
  stays a plain `String`, `.value` persisted).
- ✅ Per-leg rule-based classification, confidence bands, decline-code lookup
  table (`decline_codes.py`), §3.2.4 mandate-type fact overrides.
- ✅ `DIAGNOSING → PLAYBOOK_ACTIVE` vs `DIAGNOSING → ESCALATED_TO_HUMAN` routing
  on `PolicyConfig.diagnosis_confidence_threshold` (0.65).
- ✅ `suggested_timing_adjustment` (payday-cycle heuristic) emission → new case
  column (migration 0014).
- ✅ Writing `DIAGNOSIS_COMPLETED` `CaseEvent`s; `is_hard_decline` set (D-058).

Still deferred within Module 3's area:
- 🔧 **The §5.3 first-touch MAC-code → tier lookup at diagnosis time** (D-083).
  Module 3 *consumes* an existing `network_directive_tier` but does not extract a
  raw MAC code from the Event or call `MacCodeRegistry` — no MAC code is surfaced
  for it to look up, and issuer/network extraction is U-08. Unblocked only when
  U-08 is resolved.
- 🔮 §3.1 root-cause taxonomy refinement (the enum is the "operative demo set";
  "Module 3 owns future refinement"). The demo decline-code / B2B-bucket seed
  tables are pre-production-checklist data, same posture as `MacCodeRegistry`
  (Decision M / Part E item 1).

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
