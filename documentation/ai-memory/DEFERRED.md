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

## Module 4 — Policy & Playbook Engine — ✅ COMPLETE (runtime)

Built in the Module 4 run (`torque.policy`). Now **DONE**:
- ✅ The **playbook catalog** — the eleven §4.1 `Playbook` rows, ORM-seeded via
  `torque.policy.catalog.seed_catalog` (D-085), one per non-trivial root cause.
- ✅ **`PlaybookRun` instantiation** — `activate_case`: selection, version pinning
  at creation (INV-39), `active_step_id = entry`, `status = RUNNING`; no-playbook /
  disabled → `ESCALATED_TO_HUMAN` (D-086).
- ✅ The **rules for reading** the graph — `torque.policy.traversal` (`entry_step_id`,
  `next_step_id`, `is_terminal`, `node`, `step_template`).
- ✅ **`payday_cycle_override_enabled`** *policy gate* — `torque.policy.payday`
  (D-087); reads the merchant flag and returns whether/what to apply.
- ✅ **`multi_case_template`** contract — `step_template(node, multi_case)` returns
  the multi template or the single template + a defer signal (§4.4).

Still deferred (these are **Module 5**, the execution half — not Module 4's job):
- 🔧 Runtime graph-traversal **execution** — actually advancing `active_step_id`
  through the DB as actions fire (Module 4 provides the pure rules; Module 5 drives
  them).
- 🔧 `step_timing_semantics` **execution** / fire-time computation — offset from the
  previous step's completion, defer to the next `allowed_hours` window, never fire
  early/skip (D-025 assigns this to Module 5).
- 🔧 The payday-cycle **runtime substitution** — computing the payday-adjusted fire
  time from the signal Module 4's policy gate approves (§4.3, Module 5).
- 🔧 `multi_case_context` **rendering** — interpolating both cases' amounts via
  `ActionCase` at send time (Module 5/6 Outreach Coordinator).
- 🔧 Action-specific `params` **schemas** — still deferred; the blueprint keeps
  `ActionTemplate.params` freeform (decision E) and assigns execution-time param
  validation to Module 5.
- 🔧 The **Module 3 → Module 4 auto-dispatch trigger** (D-088) — the engine + task
  are ready and invocable, but no diagnosis-completion code enqueues
  `activate_case_task`; the cross-module trigger is an orchestration-layer concern.

## Module 5 — Execution / Orchestration — ✅ COMPLETE

Built in the Module 5 run (`torque.execution`, Postgres-polling driver, D-090).
The following are now **DONE**:
- ✅ Durable execution driver — **Postgres-polling** (§5.6): `scheduled_job` table
  (migration 0015) + stratified 10 s/60 s Celery-beat pollers, `FOR UPDATE SKIP
  LOCKED`. (Temporal was the alternative; U-07 resolved to polling, D-090.)
- ✅ The runtime tick (`execute_due_job`) — the §5.1 loop end-to-end: guardrails →
  execute → atomic Action+CaseEvent → `STEP_TRANSITIONED` → advance
  `active_step_id` → reschedule / finalize.
- ✅ The §5.2 **guardrail check sequence** (Module-5 half, D-092) for
  `RETRY_PAYMENT` and customer-contact actions, first-failure-wins.
- ✅ **Retry-rail enforcement** — Card/UPI/NACH predicates now *block* a retry, and
  Card/UPI counters are consumed once per fired retry (row-locked, INV-46).
- ✅ **Pre-debit self-heal** — auto-insert a `SEND_PRE_DEBIT_NOTIFICATION` ahead of
  a subscription retry when `gap_satisfied` is false (§5.2.3).
- ✅ Timing (D-025): offset-from-completion, `allowed_hours` deferral, payday
  substitution, UPI peak-window re-defer.
- ✅ `STEP_TRANSITIONED` audit (U-02 settled, D-091).

Still deferred within Module 5's area:
- 🔧 **Real channel adapters** (§5.4) — Meta WhatsApp, Resend, Fast2SMS, Razorpay
  retry / Mandate Execute / NACH re-presentment / Payment Links. `executor.run_action`
  is an internal **stub** (no external I/O); this is the seam they attach to.
- 🔧 **`GENERATE_PAYMENT_LINK` execution** — creating a real `PaymentLink` row from
  a Razorpay `plink_...` (the stub records the Action only).
- 🔧 **`LOG_PROMISE` execution** — creating a `PromiseToPay` + `PROMISE_CAPTURED`.
- 🔧 **Cost** from `ChannelRateCard` (Action.cost stays nullable — Module 8/9).
- 🔧 **`MacCodeRegistry` self-healing** (§5.3) — unseeded code → default
  `TIER_2_CAPPED_RETRY` + flagged `CaseEvent` (`tier_for()` still returns `None`).
  Blocked with the first-touch MAC lookup on U-08 / D-083.
- 🔧 The **Module 4 → Module 5 auto-dispatch trigger** — `schedule_run` is not
  auto-called by `activate_case` (D-093); orchestration-layer concern.

## Module 6 — Compliance & Cross-Leg Guardrail Engine — ✅ COMPLETE

Built in the Module 6 run (`torque.coordination` package + migration 0016). Now
**DONE**:
- ✅ **`GuardrailEngine.check()`** — the single facade Module 5's tick consults
  (§6.2). Returns the four-way `GuardDecision` (D-097). Composes the existing
  predicates; §5.2 sequence first-failure-wins.
- ✅ The full **`SEND_WHATSAPP` guardrail** — gate #1 (`whatsapp_opt_in`) + gate
  #2 (`approved_template_exists`, UTILITY) + open-conversation suspension
  (`active_wa_conversation_expires_at > now` → defer past the window + human-queue
  flag, Q-F), producing `CONSENT_NOT_OBTAINED` / `TEMPLATE_NOT_APPROVED`.
- ✅ **Quiet-hours** on customer contact — defer only (never a block; Q-G).
- ✅ **Outreach Coordinator** (Part A §5) — `priority()` (Module 8 seam, D-098),
  the 4h cross-leg quiet period (defer to `quiet_period_end + timing_offset`,
  `ACTION_BLOCKED`/`OUTREACH_COORDINATOR_DEFERRED`), the live **merge** in the
  poll batch (one `Action` + multi-`ActionCase`, or primary-sends/secondary-defers
  with no `multi_case_template`), open-conversation policy.
- ✅ **Escalation-ceiling** — `runner._escalation_ceiling_hit` /
  `_escalate_on_ceiling` (§6.3): Module 6 transitions the case to
  `ESCALATED_TO_HUMAN` at `stopping_rules.escalation_ceiling` (D-100), before any
  further action, one transition only. `escalation_ceiling <= max_attempts`
  enforced at save time (INV-51).
- ✅ **Human queue** — persistent `human_queue` table (migration 0016),
  FIFO-per-merchant keyed on `case_id`, fed by the `ESCALATED_TO_HUMAN` sweep +
  escalation-ceiling + broken `PromiseToPay`, ordered by `priority()`.
- ✅ **Broken-promise routing** — `human_queue.route_broken_promise` (no per-row
  column — D-038).

Still deferred within Module 6's area:
- 🔧 The real Module 8 `(probability × amount_at_risk) ÷ cost` score —
  `torque.coordination.outreach_coordinator.priority()` is the one-function seam;
  the placeholder is `amount_at_risk` descending (D-098).
- 🔧 **`LOG_PROMISE` execution** — creating a `PromiseToPay` + `PROMISE_CAPTURED`
  is still a Module 5 deferral, so the broken-promise feeder is exercised against
  a directly-constructed `BROKEN` promise; end-to-end awaits `LOG_PROMISE`.
- 🔧 **Cross-stratum merge** — the 10 s / 60 s pollers claim disjoint job sets, so
  a merge pair split across them (or across two workers of one stratum) sends solo
  (the safe un-merged baseline, not a double-send). Documented in `merge.py` /
  D-102; widening it needs cross-stratum coordination the §5.6 fallback lacks.
- 🔧 **Per-node WhatsApp template category** — the gate checks for an approved
  UTILITY template; the catalog nodes carry no category.
- 📋 **Agent Console** manual override (pause / cancel / resolve) over queue
  entries, `escalation_resolution`, `HUMAN_RESOLVED` — Module 10 (Q-I). Module 6
  only routes cases *into* the queue.

## Module 7 — Payment Reconciliation & Attribution — ✅ COMPLETE

Built in the Module 7 run (`torque.reconciliation` package, no migration). Now
**DONE**:
- ✅ Matching `payment.captured` / `subscription.charged` / `payment_link.paid` /
  `.partially_paid` to open cases (§7.1): direct `PaymentLink` →
  `AGENT_ASSISTED` / weight 1.0; indirect `(merchant, counterparty, amount)` +
  24h `Action` window (`PolicyConfig.attribution_window_hours`) → `AGENT_ASSISTED`
  / `SELF_RECOVERED`; merged-set proportional `credit_weight` re-split; non-merged
  multi-match → `AMBIGUOUS`; no-match → `DETECTED/DIAGNOSING → CANCELLED` /
  `SELF_RECOVERED` (§7.1.4).
- ✅ Writing `RevenueLeakCase.recovery_type` / `recovered_amount` via
  `guards.module7_writer` (INV-53).
- ✅ `ActionCase.credit_weight` re-split at reconciliation (§7.1.3, INV-50/12).
- ✅ Case closure — `RECOVERED` (full) / B2B `PARTIALLY_RECOVERED` with
  oldest-first invoice waterfall + `amount_at_risk` = `Σ outstanding` (INV-55) +
  the two-hop final settlement — and `PAYMENT_RECONCILED` `CaseEvent`.
- ✅ State-machine edges `DETECTED → CANCELLED`, `DIAGNOSING → CANCELLED`
  (D-103, U-01 fully resolved).
- ✅ Webhook-driven `PaymentLink.status` / `amount_paid` / `paid_at` from
  `payment_link.*` (incl. `expired` / `cancelled` → row status only,
  `LINK_UPDATED`); a row is created for an unknown link carrying a
  `notes.torque_case_id`.
- ✅ Wired into `torque.api.webhooks` dispatch (D-104), no buffer;
  `human_queue.remove_for_case` on close (D-107).

Still deferred within Module 7's area:
- 🔧 **`GENERATE_PAYMENT_LINK` execution** (Module 5) still doesn't *create*
  `PaymentLink` rows — the §7.1.1 direct path lights up fully only once it does.
  Module 7 already updates existing rows and creates one from a Torque case ref.
- 🔧 **`WRITTEN_OFF`** — the `ESCALATED_TO_HUMAN → WRITTEN_OFF` close is a
  human-only outcome (Module 10); Module 7 drives only
  `ESCALATED_TO_HUMAN → {RECOVERED, PARTIALLY_RECOVERED}` on a payment.
- 🔧 A `(merchant_id, counterparty_id)` composite index on `revenue_leak_case` —
  not added (demo scale; D-108).

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
