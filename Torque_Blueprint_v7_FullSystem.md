# Torque — Full System Blueprint v7
## All 13 Modules, Self-Contained Reference

> - **Part A** — Module 1: Core Data Model — entities, enums, decisions.
> - **Part B** — Modules 2–13: ingestion, diagnosis, policy, execution, compliance, reconciliation, scoring, reporting, UI, infra, roadmap, demo script.
> - **Part C** — Additions to Module 1 surfaced while specifying later modules.
> - **Part D** — Decisions that need your input before proceeding further.
> - **Part E** — System-wide open items.

---

# PART A — MODULE 1: CORE DATA MODEL

---

## 0. Locked Vision

**Pitch:** An agent that closes the revenue leakage loop across all four legs of the funnel — degrading payments, abandoned checkouts, failed subscriptions, and overdue B2B invoices — by diagnosing root cause, selecting a bounded recovery playbook, executing it, and reporting exactly how much money came back, how, and what it couldn't fix.

**The four legs (shared engine, leg-specific config):**
1. **Payment degradation** — soft/hard declines, issuer/network failures on live payments
2. **Checkout abandonment** — drop-off before or during payment
3. **Subscription / mandate failure** — UPI AutoPay, NACH, card recurring
4. **B2B receivables** — overdue invoices, dunning, promise-to-pay

**Differentiators (keep these honest — the build must back them, not just the pitch):**
- **Root-cause diagnosis**, not templated triggers.
- **One case object, one ledger**, across all four legs.
- **Incrementality-aware measurement** — lift over a held-out control, not gross "messaged-then-paid" totals.
- **Compliance-by-construction** — quiet hours, consent logging, promise-broken de-escalation, full audit trail.
- **Resource-aware prioritization** — chase `(probability × amount) ÷ cost`, not everyone equally.

**Build constraint (locked, overrides some "correct" recommendations below — every override is flagged where it applies):** everything built runs on free tiers. No paid services, no commercial agreements, no per-message spend outside our control.
- Self-hosted Temporal: free (MIT license) — but standing up a distributed workflow cluster is a real engineering time cost, not a licensing one (see Decision C).
- WhatsApp Business API: customer-initiated "service" conversations (and utility replies inside that 24h window) are free and uncapped. Business-initiated nudges are billed per message (~$0.01–0.02/utility message in India) the moment they fire. Demo path: Meta developer test number + pre-verified test recipients — real delivery, zero cost, capped reach (see Decision I).
- Card Account Updater (CAU): requires a commercial Visa/Mastercard/processor agreement. No free tier exists. **Excluded from the build. Roadmap only.**
- Postgres, Redis, BullMQ/Celery, econml, scikit-uplift: free, no caveat.

---

## 1. Module Map

| # | Module | What it decides | Status |
|---|---|---|---|
| 1 | **Core Data Model** | Shared case object; multi-tenancy; PII/DPDP; event sourcing; card/UPI/NACH network compliance entities | 🔒 **This document** |
| 2 | Signal Ingestion | Webhook intake; signature verification; idempotency; out-of-order handling; cross-leg dedup; systemic outage detection | ⬜ |
| 3 | Diagnosis Engine | Root cause classification with confidence scoring; MAC/network directive handling; `root_cause_code` enum lives here | ⬜ |
| 4 | Policy & Playbook Engine | Root cause → bounded, branching action graph; payday-cycle timing heuristics; multi-case rendering | ⬜ |
| 5 | Execution / Orchestration | Channel adapters; `CardRetryBudget`/`UPIRetryBudget`/`NACHRetryPolicy` enforcement; `MacCodeRegistry` population against live acquirer data | ⬜ |
| 6 | Compliance & Cross-Leg Guardrail Engine | Quiet hours; two-gate WhatsApp consent; outreach coordinator (priority formula, merge, defer) | ⬜ |
| 7 | Payment Reconciliation & Attribution | Matches payments to open cases; `AGENT_ASSISTED` vs `SELF_RECOVERED`; reads `PaymentLink`, writes `ActionCase.credit_weight` | ⬜ |
| 8 | Recovery Scoring Model | `(probability × amount) ÷ cost`; leg-type × bucket cold-start lookup; upgrade path to XGBoost + meta-learners | ⬜ |
| 9 | Reporting & Measurement | ₹ recovered, incrementality lift with confidence intervals, SUTVA cross-merchant footnote, exception list | ⬜ |
| 10 | UI/UX | Merchant dashboard, agent explainability console (renders `CaseEvent.reasoning`), demo surface | ⬜ |
| 11 | Tech Stack & Infra | Temporal (OSS) for `PlaybookRun` + BullMQ for ingestion; stratified polling fallback | ⬜ |
| 12 | Build Roadmap | Day-by-day plan | ⬜ |
| 13 | Demo Script / Judging Narrative | What we show, in what order | ⬜ |

Open items across all modules are tracked in Part E.

---

## 2. Cross-Cutting Architectural Decisions

These apply to every entity in Section 3 and are not restated per-entity.

### 2.1 Multi-tenancy
Every table carries `merchant_id`. 🔧 Demo: application-layer scoping via a single shared repository/query-builder layer that *always* injects `merchant_id` — no query may bypass it. 🔮 Roadmap: Postgres Row-Level Security as defense-in-depth past demo data volumes.

### 2.2 PII & DPDP
`Counterparty` is the **single source of PII** (name, phone, email) in the entire system. Every other table references `counterparty_id` only — never duplicates raw PII. Erasure = null the PII fields on one `Counterparty` row; everything else (case history, `CaseEvent` stream) stays structurally intact but de-identifies.

- DPDP Rules 2025 were notified November 13, 2025. Substantive provisions are effective **May 13, 2027** — genuine runway before this is a hard production gate.
- **Purpose-limitation consent is live now, not roadmap.** Using payment-failure data to trigger WhatsApp/email/SMS nudges is a secondary use under DPDP's purpose-limitation principle, distinct from general channel opt-in. Captured by `Counterparty.payment_failure_nudge_consent`.
- **RBI Digital Payments – E-Mandate Framework, 2026** (consolidated single instrument, RBI/DPSS/2026-27/396, dated April 21, 2026, superseding the earlier piecemeal e-mandate circulars) requires pre-debit notification ≥24h before **each** debit/retry event — not once per mandate. This is **live and mandatory**, addressed via the `PreDebitNotification` table (Section 3).
- 📋 Design-only for demo: the actual erasure-*request-intake* UI/endpoint is not built. The schema already satisfies erasure mechanically.

### 2.3 Event sourcing — single history mechanism
`CaseEvent` is the **only** place execution/audit history lives. There is no `AuditLogEntry` table and no `PlaybookRun.step_history` field — both are **eliminated**, not deprecated. If either name appears anywhere in a later module's spec or code, that is a bug to fix, not a variant to support.

**Atomicity requirement (hard, not aspirational):** every `Action` write and its corresponding `CaseEvent` write happen inside **one Postgres transaction** (`BEGIN…COMMIT`), same database instance. This is a transactional-outbox pattern with zero extra infrastructure, because both tables already live in the same Postgres instance. **No code path may write `Action` without `CaseEvent` in the same transaction.** This is a Module 5 code-review checklist item, not a design aspiration.

Similarly, `CardRetryBudget`'s counters are seeded and updated **in the same transaction** as the `RevenueLeakCase` + `Event` rows that trigger them (see Section 3, `CardRetryBudget`) — the same consistency principle applied consistently.

### 2.4 Playbook versioning
A `PlaybookRun` pins the exact `playbook_version` it started on and finishes on that version even if the playbook is edited mid-run.

### 2.5 Webhook ingestion — hard requirements (Module 1 → Module 2 handoff)
Every inbound Razorpay webhook is verified via **HMAC-SHA256 over the raw, unparsed request body** (re-serialized JSON will not match) against the dashboard-set secret, **compared in constant time**, **before** the payload is parsed or any `Event` row is written. Live and Test mode secrets are distinct — do not cross them. Requests that fail verification are **rejected with no side effects** — dropped silently, not logged as a `DEGRADED` or `SUSPICIOUS` case, and no `Event` row is written for them.

`Event.idempotency_key` is sourced from Razorpay's **`X-Razorpay-Event-Id`** header — unique per event including retries — **not derived from payload content**. Payload-derived keys risk collisions across genuinely distinct events that happen to share business-level fields.

### 2.6 Three retry rails, three different compliance postures
Card, UPI AutoPay, and NACH are governed by three structurally different bodies with three different enforcement mechanisms. None of the three should be treated as a template for the others:

| Rail | Enforcer | Mechanism | Entity |
|---|---|---|---|
| Card (Visa/Mastercard) | Card network (Mastercard TPE program) | Dual-window volume counter (10/24h, 35/30d) + MAC-tier-specific fee/behavior rules | `CardRetryBudget` + `MacCodeRegistry` |
| UPI AutoPay | NPCI | Hard cap: 1 original + 3 retries = 4 total, mandate auto-cancelled after. Separate non-peak execution window. | `UPIRetryBudget` |
| NACH / e-NACH | Individual banks (no NPCI-standardized cap) | Bank-discretionary cumulative dishonour-frequency threshold (commonly 3–5/FY), account-level, sometimes combined with cheque dishonours | `NACHRetryPolicy` |

---

## 3. Full Entity Reference

### `Merchant`
| Field | Notes |
|---|---|
| `merchant_id` | Razorpay merchant ID |
| `business_type` | D2C / SaaS / B2B services / marketplace |
| `tier` | Metro / Tier-2-3 — feeds language/tone calibration |
| `channels_enabled` | WhatsApp, email, SMS, voice (future) |
| `risk_appetite_config` | Default max attempts / escalation ceiling |

### `Counterparty`
Identity + consent only. All merchant-relationship history lives in `Merchant_Counterparty`.
| Field | Notes |
|---|---|
| `counterparty_id` | PK |
| `name`, `phone`, `email` | The **only** place raw PII lives in the entire system |
| `whatsapp_opt_in` | Consent gate #1 of 2 for WhatsApp (gate #2 is template approval — see `MerchantWhatsAppTemplate`) |
| `payment_failure_nudge_consent` | Purpose-limitation gate — separate from `whatsapp_opt_in`. Pre-seeded `true` in demo synthetic data; required at onboarding in production. |
| `language_pref` | `HINGLISH` \| `ENGLISH` |
| `consent_log` | Timestamped opt-in/opt-out history |

### `Merchant_Counterparty`
Join entity making relationship data merchant-scoped; also carries the incrementality cohort assignment and the WhatsApp conversation window.
| Field | Notes |
|---|---|
| `id` | PK |
| `merchant_id`, `counterparty_id` | FK, unique together |
| `payment_history_summary` | Scoped to *this* merchant relationship |
| `promise_keeping_rate` | Scoped — feeds Module 8 Recovery Scoring |
| `risk_score` | Scoped |
| `in_control_cohort` | Bool — assigned **once per merchant-relationship**, persists across every leg. Fixes case-level randomization contamination: a counterparty cannot be treatment on one case and control on another for the same merchant. |
| `cohort_assigned_at` | |
| `active_wa_conversation_expires_at` | Timestamp when the current 24h WhatsApp *service* conversation window closes. Updated on every inbound message. While `now() < this`: free-form replies allowed (no template needed), billed at free service rate, and Module 6 should route to a **human agent**, not continue automated templates into a live conversation. |

### `RevenueLeakCase`
The atomic unit — every module reads and writes this.
| Field | Notes |
|---|---|
| `case_id` | PK |
| `merchant_id` | FK |
| `leg_type` | Enum — see Section 4 |
| `source_event_id` | FK → `Event` |
| `counterparty_id` | FK |
| `systemic_event_id` | Nullable FK → `SystemicEvent`. When set, playbook execution is suppressed automatically (`SYSTEMIC_HOLD` status). |
| `amount_at_risk` | ₹ |
| `status` | Enum — full state machine in Section 4 |
| `root_cause_code` / `root_cause_label` | Set by Diagnosis Engine — enum defined in Module 3 §3.1. |
| `network_directive` | Stores `{ mac_code, tier }` for the **most restrictive tier ever received** on this case, non-overridable by a later, more permissive response. Tier precedence and full seed table are in Section 4. Full per-attempt raw history lives in `CaseEvent` (`NETWORK_DIRECTIVE_RECEIVED`). |
| `diagnosis_confidence` | 0–1 float, stored on every case from day one for calibration. Routing threshold is a **policy value**, not a hardcoded literal (see Decision E). |
| `context` | Strict typed model per `leg_type` (Pydantic/Zod), stored as JSONB, validated at write time — nothing untyped is ever written here. |
| `control_group` | Derived, read-only — computed from `Merchant_Counterparty.in_control_cohort`, denormalized here to avoid per-query joins. |
| `superseded_by_case_id` | Nullable self-FK. Cross-leg dedup merge pointer (Decision D). |
| `recovery_type` | `AGENT_ASSISTED` \| `SELF_RECOVERED` \| `AMBIGUOUS` — written **only** by Module 7. |
| `opened_at` / `closed_at` | |
| `recovered_amount` | ₹ — written **only** by Module 7. |

#### Typed leg contexts (validated at ORM boundary — nothing untyped written)

**`PaymentDegradationContext`** → `decline_code, gateway, retry_count, is_hard_decline`
> `network_directive` (MAC/tier) is a **top-level field on `RevenueLeakCase`**, not nested here — every module needs to check it without a context parse.

**`CheckoutAbandonmentContext`** → `cart_id, cart_value, drop_stage, payment_method_attempted`
> `payment_method_attempted` enum: `UPI_COLLECT | UPI_INTENT | CARD | NETBANKING | BNPL | NONE`. A `UPI_COLLECT` abandonment during VPA entry has a known, specific recovery action (suggest Intent Flow) — this is a signal-derived recommendation no generic cart-recovery tool can make.

**`SubscriptionFailureContext`** → `mandate_id, mandate_type, billing_cycle, subscription_id`
> `mandate_type` enum: `UPI_AUTOPAY | NACH | CARD`. **No `pre_debit_notified_at` field here** — replaced by the `PreDebitNotification` table (per-attempt tracking, see below).

**B2B_RECEIVABLE** → no context blob. See `B2BInvoice`.

### `B2BInvoice`
One case can bundle multiple overdue invoices for the same counterparty into a single dunning thread.
| Field | Notes |
|---|---|
| `invoice_id` | PK |
| `case_id` | FK — nullable until triaged; multiple invoices can share one `case_id` |
| `merchant_id`, `counterparty_id` | FK |
| `due_date`, `days_overdue` | |
| `original_amount`, `outstanding_amount` | Supports partial payment — a ₹40k payment against a ₹1L invoice updates `outstanding_amount`, case stays `PARTIALLY_RECOVERED` |
| `gst_inclusive` | Bool |
| `payment_terms` | |

**Grouping logic (locked, no ambiguity left for Module 2 or Module 4):**
- **Trigger:** on `invoice.overdue`, Module 2 checks for an existing **open** (non-terminal-status) case with `leg_type = B2B_RECEIVABLE` for the same `(merchant_id, counterparty_id)`.
- **Found:** new `B2BInvoice` row attaches to that `case_id`. No new case created.
- **Not found:** new case created; the invoice becomes its first `B2BInvoice` row.
- **Time window:** none — deliberately not date-bounded. The point is one coherent "here's everything you owe" message. A case stops accepting new invoices only when it closes (`RECOVERED`/`WRITTEN_OFF`/`CANCELLED`); a subsequent overdue invoice then opens a fresh case.

### `Event`
| Field | Notes |
|---|---|
| `event_id` | PK |
| `merchant_id` | |
| `type` | `payment.failed`, `checkout.abandoned`, `subscription.charged.failed`, `invoice.overdue`, `payment_link.*`, etc. |
| `idempotency_key` | Unique constraint. **Sourced from `X-Razorpay-Event-Id` header** (Section 2.5) — not payload-derived. |
| `raw_payload` | |
| `received_at` | |
| `processed` | Bool |

*(Out-of-order arrival and causality windows — e.g., a `payment.success` arriving 200ms after the `payment.failed` that would've opened a case — are a Module 2 ingestion-logic concern, specified there.)*

### `MacCodeRegistry` — network-directive classification
A static config table mapping every network decline-advice code to one of four behavior tiers. This is the mechanism that lets the *architecture* stay locked while the *specific code-to-tier mapping* remains an empirically-populated, updatable list.

| Field | Notes |
|---|---|
| `network` | `MASTERCARD` \| `VISA` (Visa equivalents to be added when available — 🔮 roadmap) |
| `mac_code` | e.g. `03`, `21`, `5C`, `9G`, `40`, `41`, `24`–`30` |
| `tier` | `TIER_1_HARD_STOP` \| `TIER_2_CAPPED_RETRY` \| `TIER_3_INSTRUMENT_DEAD` \| `TIMED_RETRY` |
| `notes` | Free text — behavior rationale |

**Seed rows (locked default; full tier semantics in Section 4):**

| Code | Tier | Why |
|---|---|---|
| `03` | TIER_1_HARD_STOP | "Do not try again" — fraudulent/closed account. Mastercard bills a fee on **any** retry after this, regardless of volume counters. |
| `21` | TIER_1_HARD_STOP | "Stop recurring payment" — cardholder-cancelled. Same fee trigger as `03`. |
| `5C` | TIER_2_CAPPED_RETRY | Issuer-temporary/reversible. Counts toward the 10/24h + 35/30d volume counters; retry permitted within cap. |
| `9G` | TIER_2_CAPPED_RETRY | Same as `5C`. |
| `40` | TIER_3_INSTRUMENT_DEAD | Consumer Single-Use Virtual Card Number. **No fee attached** (per Mastercard's own MAC documentation) — but retrying is futile because the instrument cannot support recurring charges. Route to "request new payment method," don't go silent. |
| `41` | TIER_3_INSTRUMENT_DEAD | Non-reloadable prepaid. Same behavior as `40`. |
| `24` | TIMED_RETRY | Retry after 1 hour |
| `25` | TIMED_RETRY | Retry after 24 hours |
| `26` | TIMED_RETRY | Retry after 2 days |
| `27` | TIMED_RETRY | Retry after 4 days |
| `28` | TIMED_RETRY | Retry after 6 days |
| `29` | TIMED_RETRY | Retry after 8 days |
| `30` | TIMED_RETRY | Retry after 10 days |

**Explicitly NOT yet seeded** (open — see Part E, item 1): `01, 02, 04, 05, 07, 19, 22, 39, 42, 43, 51, 52, 53, 57, 59, 61, 62, 65, 75, 78, 79, 82, 83, 86, 91, 93, 96`, plus the full Visa equivalent set. These must be validated against Razorpay's actual live acquirer-level output before production traffic — this is a **Module 5 checklist item**, not an architectural gap (Decision M).

### `CardRetryBudget`
Enforces Mastercard's dual-window volume limit. **Applies only when the payment instrument is a card** (`mandate_type = CARD` or a non-subscription card payment) — never consulted for NACH or UPI AutoPay.
| Field | Notes |
|---|---|
| `budget_id` | PK |
| `card_token_hash` | Tokenized card identifier — never raw PAN |
| `merchant_id` | |
| `attempts_used_24h` | Int, rolling 24h window |
| `attempts_used_30d` | Int, rolling 30-day window |
| `hard_stop` | Bool — `true` only for `TIER_1_HARD_STOP` and `TIER_3_INSTRUMENT_DEAD` MACs |
| `hard_stop_reason` | `NETWORK_HARD_STOP` (Tier 1) \| `INSTRUMENT_NOT_RECURRING_CAPABLE` (Tier 3) — kept as two distinct reasons because they route to two different downstream actions (stop all contact vs. ask for a new payment method) |

**Seeding (critical — avoids an off-by-one against the network's actual count):** counters are **not** seeded at zero. When Module 2 ingests the *originating* declined-payment event that creates the `RevenueLeakCase`, that same ingestion event increments `attempts_used_24h`/`attempts_used_30d` to 1 (upserting the row), **in the same transaction** as the `RevenueLeakCase` + `Event` insert. Every subsequent Module 5 `RETRY_PAYMENT` action increments the same row. This keeps Torque's count aligned with what Mastercard is actually counting from the first decline, not from Torque's first retry.

**Pre-retry check (Module 5):** `attempts_used_24h < 10 AND attempts_used_30d < 35 AND hard_stop = false`.

### `NACHRetryPolicy`
NACH has **no NPCI-standardized fixed attempt cap** — this is a structurally different compliance posture from card and UPI, stated explicitly rather than left to be inferred.
| Field | Notes |
|---|---|
| `nach_retry_policy_id` | PK |
| `mandate_id` | FK |
| `clearing_cycle_status` | `PENDING_CLEARING` \| `RETURNED` \| `CLEARED` — NACH returns take 3–7 banking days, batch clearing, not real-time |
| `return_reason_code` | NPCI NACH return reason (e.g., insufficient funds, account closed) |
| `retry_eligible_after` | Date of next batch clearing window |
| `dishonour_count_this_fy` | Int, running counter per mandate — a conservative proxy, since Torque has no visibility into a counterparty's dishonour history on *other* instruments at the same bank |

**Posture:** Individual banks track dishonour frequency **per financial year** (commonly a 3–5 occurrence threshold before consequences like mandate-registration refusal), at the **account level**, sometimes combined with cheque dishonours on the same account. `Playbook.stopping_rules.max_attempts` for NACH playbooks carries a **merchant-configurable ceiling, recommended default 3 representments per billing cycle** — explicitly a **self-imposed** ceiling chosen to stay conservative under typical bank thresholds, not a network-enforced number the way `UPIRetryBudget.hard_cap` is. Cross-instrument (cheque + NACH combined) aggregation is 🔮 roadmap — requires bank-side visibility Torque doesn't have.

### `UPIRetryBudget`
Enforces NPCI's UPI AutoPay rules — two **independent** constraints, both must pass.
| Field | Notes |
|---|---|
| `budget_id` | PK |
| `mandate_id` | FK — scoped per-mandate (UPI AutoPay has no card token) |
| `attempts_used` | Int, includes the original attempt |
| `hard_cap` | Constant `3` (retries only; 4 total with the original) — NPCI-enforced, not merchant-configurable |
| `mandate_cancelled_at` | Set by Module 2 when NPCI confirms cancellation post-4th attempt |
| `permitted_execution_window` | The complement of NPCI's declared peak window: **peak = 10:00–13:00 and 17:00–21:30 IST**; permitted execution = outside these hours |

**Two independent gates, both required:**
1. `attempts_used < 3 AND mandate_cancelled_at IS NULL` — the attempt-count gate.
2. `current_time NOT IN [10:00–13:00, 17:00–21:30] IST` — the execution-window gate. **This is not the same thing as `Playbook.stopping_rules.allowed_hours`** — `allowed_hours` governs when it's acceptable to *contact* the customer (a UX/compliance choice); `permitted_execution_window` governs when NPCI's infrastructure will accept the *debit attempt itself*. A retry at 11:00 could sit fine inside `allowed_hours` and still fall inside NPCI's peak window — passing one does not imply passing the other.

**Playbook-validation-time rule:** a Leg 3 UPI AutoPay playbook configured for more than 3 retries **fails validation at save time**, not silently at runtime.

### `PreDebitNotification`
Replaces the earlier single-field approach entirely — this is a per-attempt table, not a single timestamp on the case.
| Field | Notes |
|---|---|
| `notification_id` | PK |
| `case_id` | FK |
| `notified_at` | Timestamp of this specific pre-debit notification |
| `covers_attempt_number` | Which retry attempt this notification authorizes |
| `channel` | How it was sent |
| `notified_amount` | The ₹ amount actually communicated to the customer — can legitimately differ from the original mandate amount (proration, partial-recovery scenarios) |

Only ever represents **Torque-initiated retry notifications** — not the original merchant/PSP failure notice, which is a separate, out-of-scope event. Compliance reference: RBI Digital Payments – E-Mandate Framework, 2026.

**Guardrail check (Module 6):** `EXISTS (SELECT 1 FROM PreDebitNotification WHERE case_id = X AND covers_attempt_number = next_attempt AND now() - notified_at >= 24h)`.

### `SystemicEvent`
Detects outage-scale failure spikes and suppresses individual-case outreach during them. Two independent detection tiers.
| Field | Notes |
|---|---|
| `systemic_event_id` | PK |
| `issuer_code` / `network` | Which bank/network is affected; nullable when `scope = NETWORK_WIDE` |
| `scope` | `ISSUER_SPECIFIC` \| `NETWORK_WIDE` |
| `failure_rate_at_detection` | Failures/min when threshold was crossed |
| `detected_at` | |
| `resolved_at` | Nullable — see sustain-window rule below |
| `affected_case_count` | Denormalized count for reporting |

**Threshold (compound, not a bare ratio):** `failure_rate ≥ 5× rolling_10min_baseline AND baseline_rate ≥ N failures/min AND absolute_failure_count ≥ M in the detection window`. `N` and `M` are per-issuer (for `ISSUER_SPECIFIC`) or per-merchant-aggregate (for `NETWORK_WIDE`) config values — not hardcoded — but they now exist in the spec, closing the cold-start false-positive gap for new/low-volume merchants.

**`NETWORK_WIDE` tier exists because a per-issuer-only check can miss a proportional, simultaneous spike across every issuer** — India's UPI infrastructure has experienced multiple network-wide outages (not concentrated on any single bank) within short windows. The `NETWORK_WIDE` check compares **aggregate failure rate across all issuers** against the **merchant's own historical aggregate baseline**, independent of whether any single issuer crosses its own 5× threshold.

**Resolution:** `resolved_at` requires a **sustain window** — failure rate must stay below threshold for **Y consecutive minutes** (default 10, config value) before it's written. This prevents `SYSTEMIC_HOLD → DIAGNOSING → SYSTEMIC_HOLD` flapping on intermittent outages.

Cases with `systemic_event_id` set are held at `SYSTEMIC_HOLD` (all outreach suppressed) and re-queued for diagnosis in a batch when `resolved_at` is written.

### `CaseEvent`
The **single** audit/history mechanism for the entire system. Replaces `AuditLogEntry` and `PlaybookRun.step_history` completely — both are eliminated, not deprecated.
| Field | Notes |
|---|---|
| `event_seq_id` | PK, auto-incrementing, globally ordered |
| `case_id` | FK |
| `counterparty_id` | Reference only — **no raw PII** |
| `event_type` | Enum — see Section 4 |
| `actor` | `SYSTEM` \| `AGENT` \| `HUMAN` |
| `payload` | Typed JSON per `event_type` — schema locked per type in Section 4. **No `event_type` may be written without a matching schema.** |
| `reasoning` | The explainability payload — *why* the diagnosis/decision engine made this choice. Renders directly as the UI's "Agent Reasoning" panel. |
| `timestamp` | |

**Atomicity:** every `Action` write and its `CaseEvent` write happen in one Postgres transaction (Section 2.3). No separate mechanism, no message broker, no eventual consistency gap.

### `MerchantWhatsAppTemplate`
| Field | Notes |
|---|---|
| `template_id` | Meta WABA template ID |
| `merchant_id` | FK |
| `template_name`, `category` (utility/marketing), `approval_status` | |
| `leg_type` | Which leg this template is approved for |

**Before any `SEND_WHATSAPP` action fires, Module 6 checks both:** `Counterparty.whatsapp_opt_in = true` **AND** an approved template of the right category exists for this `leg_type`. Either failure produces `Action.outcome = BLOCKED_BY_GUARDRAIL` with `block_reason = CONSENT_NOT_OBTAINED` or `TEMPLATE_NOT_APPROVED` — both surfaced in Module 9's exception report.

### `Playbook`
| Field | Notes |
|---|---|
| `playbook_id` | PK |
| `leg_type`, `trigger_condition` | |
| `steps_graph` | **Format locked** (Module 4 writes it, Module 5 traverses it — this is their shared contract): `{ "entry": "s1", "nodes": [ { "id": "s1", "action_template": "SEND_WHATSAPP", "timing_offset_hours": 0, "params": {...} } ], "edges": [ { "from": "s1", "condition": "on_success", "to": "s3" }, { "from": "s1", "condition": "on_blocked", "to": "s2" } ] }`. Conditions: `on_success`, `on_no_response`, `on_blocked`, `on_failed`. Every node has exactly one `on_success` edge and at least one fallback. Terminal nodes trigger stopping-rule evaluation. |
| `step_timing_semantics` | Each `timing_offset_hours` is measured from the **previous step's actual completion timestamp**. If the computed fire-time falls outside `stopping_rules.allowed_hours`, execution **defers to the next allowed window** — never fires early, never silently skips. |
| — payday-cycle heuristic | For `root_cause_code: NSF_SOFT_DECLINE` on debit cards, the Diagnosis Engine (Module 3) produces a `suggested_timing_adjustment` (with attached `diagnosis_confidence`) toward the next salary-credit date. Module 4 applies it **by default**, gated by a per-merchant config flag `payday_cycle_override_enabled` (default `true`) — a merchant with irregular-pay counterparties (gig/contract workers) can disable it. **This is a suggested heuristic, not a mandatory substitution** — it does not override merchant configuration. |
| `stopping_rules` | `max_attempts` (merchant-configurable ceiling — **capped at ≤3 for UPI AutoPay playbooks at validation time**, network-metered separately for card via `CardRetryBudget`), `max_duration_days`, `allowed_hours` (e.g. `08:00–19:00 IST`), `escalation_ceiling` |
| `version` | Runs pin to the version they started on |

### `PlaybookRun`
| Field | Notes |
|---|---|
| `run_id` | PK |
| `case_id`, `playbook_id`, `playbook_version` | FK |
| `active_step_id` | Current position in the graph — a single pointer, **not a log**. |
| `status` | `RUNNING` \| `PAUSED` \| `COMPLETED` \| `HALTED_BY_GUARDRAIL` \| `ESCALATED` \| `CANCELLED` |

**There is no `step_history` field.** Every step-entered/exited/outcome event is a `CaseEvent` with `event_type = STEP_TRANSITIONED`.

### `Action`
| Field | Notes |
|---|---|
| `action_id` | PK |
| `primary_case_id` | FK — the lead case this action is attributed to |
| `run_id` | FK |
| `action_type` | Enum — Section 4 |
| `channel` | |
| `content_sent` | Rendered message — references `counterparty_id` only, no embedded PII; redacted on erasure cascade |
| `executed_at` | |
| `outcome` | Enum — Section 4 |
| `block_reason` | Populated when `outcome = BLOCKED_BY_GUARDRAIL` — enum in Section 4 |
| `cost` | ₹ — from `ChannelRateCard`. Demo: real delivery to pre-verified test numbers, seeded realistic rates, **actual spend $0**. |

**There is no `merged_case_ids` array field.** Multi-case actions use `ActionCase` below.

### `ActionCase`
Replaces the earlier array-field approach for actions that address more than one case at once (the outreach coordinator's merge behavior — Section 5).
| Field | Notes |
|---|---|
| `action_id` | FK |
| `case_id` | FK |
| `is_primary` | Bool — exactly one `true` per action |
| `credit_weight` | 0–1 float — Module 7 splits recovery credit proportionally instead of guessing |

**Constraint (enforced, not just documented):** the sum of `credit_weight` across all `ActionCase` rows sharing an `action_id` **must equal exactly 1**. Implemented as a database check constraint, or — where the DB can't express a cross-row sum directly — an application-layer validation in the same transaction as the `ActionCase` inserts.

### `PaymentLink`
| Field | Notes |
|---|---|
| `link_id` | PK — Razorpay's `plink_...` ID |
| `action_id`, `case_id` | FK |
| `status` | `issued` \| `partially_paid` \| `paid` \| `expired` \| `cancelled` |
| `amount_paid` | Updated by webhook |
| `expires_at`, `paid_at` | |

Populated by Module 2 subscribing to `payment_link.paid`, `payment_link.partially_paid`, `payment_link.expired`, `payment_link.cancelled` (same signature-verification requirement as every other inbound webhook, Section 2.5). Module 7 reads `PaymentLink.status` to determine `AGENT_ASSISTED` vs `SELF_RECOVERED` — this is the single most important attribution signal in the system, and it is now visible instead of inferred.

### `PromiseToPay`
| Field | Notes |
|---|---|
| `case_id` | FK |
| `promised_amount`, `promised_date` | |
| `captured_via` | Which `Action` captured this |
| `status` | `PENDING` \| `KEPT` \| `BROKEN` |
| `on_broken` | Routes to a **human queue** — never triggers a harsher automated message. |

### `ChannelRateCard`
| Field | Notes |
|---|---|
| `channel` | |
| `rate_per_unit` | Static config seeding `Action.cost`. Demo: seeded from realistic WhatsApp/SMS/email pricing so cost arithmetic is correct even though actual demo spend is $0 (test-tier delivery). |

### ⚠️ Eliminated entity — do not recreate
**`AuditLogEntry`** — removed as of this revision's predecessor. Fully replaced by `CaseEvent`. If any future module document references `AuditLogEntry`, treat it as a stale reference and fix it, not as a parallel table to maintain.

---

## 4. Complete Enums Reference

### `leg_type`
`PAYMENT_DEGRADATION` | `CHECKOUT_ABANDONMENT` | `SUBSCRIPTION_FAILURE` | `B2B_RECEIVABLE`

### `mandate_type` (on `SubscriptionFailureContext`)
`UPI_AUTOPAY` | `NACH` | `CARD`

### `RevenueLeakCase.status` — full state machine
```
DETECTED → SYSTEMIC_HOLD          (if Module 2 detects an outage wave)
         → DIAGNOSING → PLAYBOOK_ACTIVE → RECOVERED
                                        → PARTIALLY_RECOVERED
                                        → EXHAUSTED
                                        → ESCALATED_TO_HUMAN → RECOVERED         (human resolves)
                                                              → PARTIALLY_RECOVERED
                                                              → WRITTEN_OFF
                                        → PAUSED   (merchant intervening manually; re-entry to PLAYBOOK_ACTIVE on un-pause)
                                        → CANCELLED (customer self-paid; recovery_type = SELF_RECOVERED, terminal)

SYSTEMIC_HOLD → DIAGNOSING   (when SystemicEvent.resolved_at is set; batch re-evaluation)
```
`ESCALATED_TO_HUMAN` is **not terminal** — it carries `escalation_resolution`, written by a human agent, driving the final transition.

### MAC tier classification (`network_directive.tier`)
| Tier | Meaning | `hard_stop` | `hard_stop_reason` | Policy behavior |
|---|---|---|---|---|
| `TIER_1_HARD_STOP` | Fee-on-first-retry, do-not-retry (e.g. MAC 03, 21) | `true` | `NETWORK_HARD_STOP` | Stop all contact tied to this payment method, permanently |
| `TIER_2_CAPPED_RETRY` | Reversible/temporary, volume-metered only (e.g. MAC 5C, 9G) | `false` | — | Counts toward `attempts_used_24h`/`_30d`; retry permitted within cap |
| `TIER_3_INSTRUMENT_DEAD` | No fee, but instrument structurally cannot support recurring (e.g. MAC 40, 41) | `true` | `INSTRUMENT_NOT_RECURRING_CAPABLE` | Distinct branch: stop retrying *this instrument*, route immediately to "request new payment method" — not silence |
| `TIMED_RETRY` | Issuer-specified retry-after window (MAC 24–30) | `false` | — | Honor the specified window |

**Precedence when a single case receives codes from more than one tier across attempts (most → least restrictive):** `TIER_1_HARD_STOP > TIER_3_INSTRUMENT_DEAD > TIER_2_CAPPED_RETRY > TIMED_RETRY > null`. Once set, `network_directive` never downgrades to a less restrictive tier. *(Tier 1/Tier 3 ordering is a stated default, not yet independently confirmed — see Part E.)*

Full seed rows for `MacCodeRegistry` are in Section 3.

### `Action.action_type`
`RETRY_PAYMENT` | `SEND_PRE_DEBIT_NOTIFICATION` | `SEND_WHATSAPP` | `SEND_EMAIL` | `SEND_SMS` | `GENERATE_PAYMENT_LINK` | `LOG_PROMISE` | `ESCALATE_HUMAN` | `SYSTEMIC_HOLD`

### `Action.outcome`
`SUCCESS` | `FAILED` | `NO_RESPONSE` | `BLOCKED_BY_GUARDRAIL`

### `Action.block_reason`
| Value | Trigger |
|---|---|
| `CONSENT_NOT_OBTAINED` | `MerchantWhatsAppTemplate` gate — no opt-in |
| `TEMPLATE_NOT_APPROVED` | `MerchantWhatsAppTemplate` gate — no approved template |
| `CARD_NETWORK_LIMIT` | `CardRetryBudget` volume cap exceeded |
| `NETWORK_HARD_STOP` | `CardRetryBudget.hard_stop = true`, Tier 1 |
| `QUIET_HOURS` | Outside `stopping_rules.allowed_hours` |
| `OUTREACH_COORDINATOR_DEFERRED` | Section 5 defer policy |
| `SYSTEMIC_HOLD` | Case under an active `SystemicEvent` |
| `PRE_DEBIT_GAP_NOT_MET` | `PreDebitNotification` 24h gap not satisfied |
| `UPI_RETRY_CAP_EXCEEDED` | `UPIRetryBudget.attempts_used ≥ 3` |
| `UPI_EXECUTION_WINDOW_CLOSED` | Inside NPCI peak window (10:00–13:00, 17:00–21:30 IST) |
| `NACH_CEILING_REACHED` | `NACHRetryPolicy` self-imposed representment ceiling reached |

### `CaseEvent.event_type` and payload schema
| `event_type` | `payload` shape |
|---|---|
| `STATUS_CHANGED` | `{ from_status, to_status, trigger }` |
| `DIAGNOSIS_COMPLETED` | `{ root_cause_code, diagnosis_confidence, network_directive }` |
| `ACTION_EXECUTED` | `{ action_type, channel, outcome, cost }` |
| `ACTION_BLOCKED` | `{ action_type, block_reason }` |
| `NETWORK_DIRECTIVE_RECEIVED` | `{ mac_code, tier, attempt_number, received_at }` |
| `PROMISE_CAPTURED` | `{ promised_amount, promised_date }` |
| `PAYMENT_RECONCILED` | `{ recovered_amount, recovery_type }` |
| `SYSTEMIC_HOLD_APPLIED` | `{ systemic_event_id, issuer_code, scope }` |
| `HUMAN_RESOLVED` | `{ resolution, agent_id }` |
| `STEP_TRANSITIONED` | `{ from_step_id, to_step_id, edge_condition, outcome }` — proposed default, not yet independently confirmed (see Part E) |

No `event_type` may be written without a matching schema in this table.

### `recovery_type`
`AGENT_ASSISTED` | `SELF_RECOVERED` | `AMBIGUOUS`

### `PromiseToPay.status`
`PENDING` | `KEPT` | `BROKEN`

### `PlaybookRun.status`
`RUNNING` | `PAUSED` | `COMPLETED` | `HALTED_BY_GUARDRAIL` | `ESCALATED` | `CANCELLED`

### `PaymentLink.status`
`issued` | `partially_paid` | `paid` | `expired` | `cancelled`

### `CheckoutAbandonmentContext.payment_method_attempted`
`UPI_COLLECT` | `UPI_INTENT` | `CARD` | `NETBANKING` | `BNPL` | `NONE`

---

## 5. Outreach Coordinator — Full Specification (Module 6 preview)

Prevents two concurrent playbook runs from both firing at the same counterparty. This spec lives here because it directly affects the `ActionCase` schema and must be agreed before Module 6 is written.

**Priority when two cases compete for a counterparty's outreach slot:** `(probability × amount_at_risk) ÷ cost`, computed per case — the **same formula that governs prioritization everywhere else in the system**. `probability` sources from the Module 8 leg-type × bucket lookup table. Leg type is not a separate override — it's already implicitly encoded in the probability estimate (a fresh subscription failure scores higher than a 90-day-overdue invoice). *(An earlier fixed leg-type ordering — B2B > Subscription > Payment > Checkout — was replaced by this formula, because a fixed ordering let a ₹500 invoice outrank a ₹50,000 subscription failure by fiat, contradicting the resource-aware prioritization differentiator.)*

**Minimum quiet period:** 4 hours between any two outreach events from **different legs** to the same counterparty within the same merchant. Within a single leg's own playbook, the playbook's own `timing_offset` governs — the coordinator adds no extra delay there.

**Merge policy:** if two cases from the same merchant are both awaiting their next outreach step for the same counterparty at the same time, they merge into a single `Action` with both `case_id`s represented via `ActionCase` rows (`is_primary` on the higher-priority case, `credit_weight` split per Module 7's attribution rules). The message references both outstanding amounts. Requires playbook step templates to support a `multi_case_context` rendering mode — flagged for Module 4.

**Defer policy:** if a case's scheduled outreach would fire within the 4-hour quiet period after another leg's action, it is **deferred** to `quiet_period_end + timing_offset` — never skipped, never cancelled. A `CaseEvent` of type `ACTION_BLOCKED` with `block_reason = OUTREACH_COORDINATOR_DEFERRED` is written.

**Open-conversation policy:** if `Merchant_Counterparty.active_wa_conversation_expires_at > now()`, automated template messages are **suspended** for that counterparty. A `CaseEvent` is written, and the case is flagged for human-agent pickup within the free service-conversation window.

---

## 6. Incrementality Measurement — Final State

**Randomization unit:** `Merchant_Counterparty.in_control_cohort`, assigned once per merchant-relationship, persisting across every leg. This is the fix for the original case-level contamination bug (a counterparty could not previously be treatment on one leg and control on another for the same merchant simultaneously).

**Holdout fraction:** 10–15% of counterparties per merchant, stratified by leg presence.

**SUTVA (Stable Unit Treatment Value Assumption) — final scope of the known limitation:**
- **Intra-merchant, cross-leg spillover is already resolved** by counterparty-level cohort assignment — every case for a given counterparty at a given merchant shares one cohort assignment, so a subscription-failure case and an overdue-invoice case for the same counterparty at the same merchant cannot land in different cohorts.
- **The unresolved exposure is cross-merchant only:** a business counterparty (e.g., ABC Corp) can be in the treatment cohort for Merchant X and the control cohort for Merchant Y simultaneously. If Torque's outreach to ABC Corp about Merchant X's invoice prompts their AP team to review all outstanding invoices — including Merchant Y's — the control-group case for Merchant Y "self-recovers" from treatment spillover, inflating control recovery rates and understating lift for B2B cross-merchant scenarios specifically.
- Module 9 flags any control-group counterparty that also appears in a treatment group for another merchant in the same cohort window, and the reported lift figure carries a footnote for these cases. **This bounds the measurement; it does not invalidate it.**

**Reporting:** confidence intervals are shown alongside the point lift estimate — a wide interval from a small merchant batch is honest and credible, not a weakness to hide.

---

## 7. Relationship Diagram

```
Merchant ──< Merchant_Counterparty (in_control_cohort, active_wa_conversation_expires_at) >── Counterparty (PII only)
    │                    │
    └──< RevenueLeakCase >────────────────────────────────────────┐
              │                                                   │ (counterparty_id)
              ├── source: Event (idempotency_key via X-Razorpay-Event-Id)
              ├── context: {typed model per leg_type}             │
              ├── B2BInvoice (0..n, B2B leg only)                 │
              ├── network_directive {mac_code, tier} ← MacCodeRegistry
              ├── systemic_event_id → SystemicEvent (scope: ISSUER_SPECIFIC | NETWORK_WIDE)
              ├── superseded_by_case_id → self                    │
              │                                                   │
              └──< PlaybookRun (pinned playbook_version) >── Playbook (steps_graph)
                         │
                         ├──< Action (cost ← ChannelRateCard) >──< ActionCase (credit_weight, Σ=1) >
                         │           │
                         │           └── PromiseToPay (0..1)
                         │
                         └──> CaseEvent stream (append-only; sole audit mechanism; atomic w/ Action writes)

CardRetryBudget   (card_token_hash × merchant_id) — seeded from originating decline, checked pre-RETRY_PAYMENT for CARD instruments
UPIRetryBudget    (mandate_id) — attempts_used < 3 AND outside NPCI peak window, checked pre-RETRY_PAYMENT for UPI_AUTOPAY
NACHRetryPolicy   (mandate_id) — clearing-cycle-aware, self-imposed ceiling, checked pre-representment for NACH
PreDebitNotification (case_id, per-attempt) — ≥24h gate before any subscription retry
PaymentLink       (action_id, case_id) — populated by payment_link.* webhooks, read by Module 7 for attribution
MerchantWhatsAppTemplate — two-gate WhatsApp check (consent AND template approval)
```

---

## 8. Decisions Table — Final, Re-Locked

| # | Decision | Locked default |
|---|---|---|
| A | Hackathon-scoped build, full-fidelity design doc | Confirmed. Every entity/field carries 🔧 (build)/📋 (design-only)/🔮 (roadmap) tags throughout this document. |
| B | DB / multi-tenancy | Postgres, app-layer `merchant_id` scoping for demo. RLS is 🔮 roadmap. |
| C | Job scheduler | **Temporal (OSS, self-hosted, free) for `PlaybookRun`** + **BullMQ + Redis for inbound event ingestion**. Not alternatives — different problems (durable multi-day workflow vs. high-throughput stateless intake). **Fallback if a self-hosted Temporal cluster isn't feasible in the build window:** Postgres-backed job table with a polling worker, **stratified polling frequency**: Leg 1 (payment degradation) requires sub-10-second polling on the first-retry step (live customer session); Legs 2, 3, 4 use 60-second polling (multi-day timelines make that latency immaterial). Go/no-go on Temporal itself is still open — see Part E. |
| D | Cross-leg dedup | **Merge**, not suppress. Narrower case sets `superseded_by_case_id`; its context is appended to the surviving case. No diagnostic signal thrown away. |
| E | Diagnosis confidence routing | **Policy statement, not a hardcoded float.** `diagnosis_confidence` is logged on every case from day one for calibration. Routing threshold `T` is initialized at `0.65`, explicitly labeled an **uncalibrated launch value**, and adjusted as resolved-case outcome data accumulates. |
| F | Recovery Scoring cold-start | **Leg-type × amount-bucket × days-since-failure lookup table**, seeded from published industry benchmarks: Subscription failure 0–48h → 65%; 3–7d → 45%; 7+d → 25%. Payment degradation, same-session → 55%. B2B invoice 0–30d overdue → 35%; 30–90d → 20%; 90+d → 12%. Checkout abandonment, same-session → 40%. **Upgrade path:** XGBoost + SHAP once 500+ resolved cases exist, with T-learner/X-learner meta-learners for individual uplift rather than average treatment effect. |
| G | `B2BInvoice` bundling | Confirmed. Multiple overdue invoices for one counterparty → one case, multiple `B2BInvoice` rows. Grouping trigger/criteria/window fully locked in Section 3. |
| H | DPDP erasure flow | Schema supports it (`Counterparty` as single PII source, null-on-erasure). Erasure-request UI/endpoint is 📋 design-only — not built for demo. Purpose-limitation consent (`payment_failure_nudge_consent`) **is** 🔧 built, pre-seeded `true` in demo data, flagged as a production onboarding gate. RBI E-Mandate 2026 pre-debit requirement is **live**, addressed via `PreDebitNotification`. |
| I | Demo channel delivery | WhatsApp: Meta developer test number + pre-verified test recipients, zero cost. Email: Resend free tier (3,000/month, no card required). **SMS: Fast2SMS ₹50 free-credit Quick SMS test route, no DLT required — for demo only, capped to pre-verified test numbers.** Production SMS at any real scale requires full TRAI DLT registration (Principal Entity + Sender ID + per-template approval — a multi-day process, structurally identical in kind to WhatsApp's Meta template gate). **This is 🔮 roadmap, named explicitly so it is not mistaken for solved-at-scale.** |
| J | Systemic detection threshold | Compound condition: `failure_rate ≥ 5× rolling_10min_baseline AND baseline_rate ≥ N AND absolute_count ≥ M`, `N`/`M` as per-scope config values. `resolved_at` requires a **10-minute sustain window** (config) below threshold. Now split by `scope`: `ISSUER_SPECIFIC` and `NETWORK_WIDE`, both exercised in demo via synthetic data. |
| K | Card/UPI/NACH retry-budget demo scope | `CardRetryBudget`, `UPIRetryBudget`, `NACHRetryPolicy` all 🔧 built — they're DB lookups, not heavy compute. Demo synthetic data includes: one Tier-1 hard-stop MAC blocking a card retry; one Tier-3 scenario routing to "request new payment method"; one UPI AutoPay mandate hitting its 3-retry cap; one NACH case approaching its self-imposed 3/cycle ceiling. |
| L | Webhook signature verification | HMAC-SHA256 over the raw request body, `X-Razorpay-Event-Id`-sourced idempotency, verification before parsing, failed verification silently dropped with no `Event` row and no case created. A Module 1 cross-cutting requirement, not a Module 2 afterthought. |
| M | `MacCodeRegistry` empirical validation | The four-tier *architecture* is locked. The specific code-to-tier mapping for every code Razorpay's acquirers actually return is a **Module 5 pre-production checklist item**: validate the seed table (Section 3) against live gateway output; update rows as needed. This is data population, not a redesign trigger. |

---

## 9. Known Open Items

See Part E, at the end of this document, for the current list of everything unresolved across the whole system.

---

# PART B — MODULES 2 THROUGH 13

Each module is written to be implementable directly against Part A's entities. Where a module needs a value or enum Part A didn't define (e.g., `root_cause_code`), it's defined here, in the module that owns it.

---

## Module 2: Signal Ingestion

**Purpose:** turn Razorpay webhooks (and one non-Razorpay storefront signal) into verified, deduplicated `Event` rows and, where appropriate, `RevenueLeakCase` rows — without ever acting on an unverified or duplicate signal, and without creating overlapping cases across legs for the same underlying loss.

### 2.1 Event types consumed

| Source | `Event.type` | Purpose |
|---|---|---|
| Razorpay webhook | `payment.failed` | Leg 1 trigger |
| Razorpay webhook | `payment.captured` | Out-of-order/self-recovery detection (2.3) |
| Razorpay webhook | `subscription.charged.failed` | Leg 3 trigger |
| Razorpay webhook | `subscription.charged` | Out-of-order detection for Leg 3 |
| Razorpay webhook | `invoice.overdue` | Leg 4 trigger |
| Razorpay webhook | `payment_link.paid` / `.partially_paid` / `.expired` / `.cancelled` | Feeds `PaymentLink` (Module 7 attribution) |
| Storefront signal (not Razorpay) | `checkout.abandoned` | Leg 2 trigger — see 2.6, this path is architecturally different from the rest |

### 2.2 Verification pipeline (every request, no exceptions)

1. Read the raw request body — do not parse yet.
2. Compute HMAC-SHA256 using the merchant's Live/Test webhook secret (Live and Test secrets are distinct; select by the mode the request arrived on, never cross them).
3. Compare against the `X-Razorpay-Signature` header in constant time.
4. **Mismatch → return HTTP 200, drop silently.** No `Event` row, no `CaseEvent`, no side effect of any kind. (Return 200 rather than 4xx/5xx specifically to avoid triggering Razorpay's retry-on-failure behavior for a request that will never verify — retrying it changes nothing.)
5. **Match → parse body**, extract `X-Razorpay-Event-Id`.
6. Check `Event.idempotency_key` (= `X-Razorpay-Event-Id`) for uniqueness. Exists already → return 200, no reprocessing.
7. New → proceed to dispatch (2.3).

### 2.3 Out-of-order arrival / same-session self-recovery buffer

A `payment.failed` case is not created the instant the webhook is verified. Instead:

1. Write the `Event` row (verified, deduplicated).
2. Enqueue a BullMQ delayed job, **delay = 90 seconds** (default; flagged as tunable, not empirically derived from real customer retry-latency data — a reasonable placeholder chosen because card re-authorization retries after a wrong-CVV or 3DS hiccup typically resolve within tens of seconds, not minutes).
3. When the delayed job fires, check: has a `payment.captured` event for the same `order_id`/`payment_id` arrived in the interim? If yes → mark the originating `Event.processed = true`, create **no case** (this was invisible, same-session self-recovery — correctly outside Torque's scope, since no revenue actually leaked). If no → proceed to case creation and dedup check (2.4).

Apply the same pattern to `subscription.charged.failed` with a shorter buffer (**30 seconds** default) — background auto-debits don't have the same immediate-retry UX pattern as a live checkout, but a race between a failure and success webhook for the same billing attempt is still possible.

`invoice.overdue` and `checkout.abandoned` need no buffer — both already imply enough elapsed time that an immediate self-correction pattern doesn't apply the same way.

### 2.4 Cross-leg dedup (implements Decision D: Merge)

When a `payment.failed` event survives the buffer in 2.3 and is about to open a `PAYMENT_DEGRADATION` case, check for an **open** `CHECKOUT_ABANDONMENT` case for the same `(merchant_id, counterparty_id, cart_id/order_id)` within the preceding **2 hours** (default window, tunable — chosen to cover the typical abandon-then-return-and-pay gap without capturing unrelated later sessions).

- **Found:** this is the same underlying loss surfacing under two signals. The `CHECKOUT_ABANDONMENT` case (narrower, less diagnostically specific) gets `superseded_by_case_id` pointing to a newly created `PAYMENT_DEGRADATION` case. The abandonment's `context` (`drop_stage`, `cart_value`, `payment_method_attempted`) is appended into the surviving case's diagnostic input for Module 3 — no signal is thrown away.
- **Not found:** create the `PAYMENT_DEGRADATION` case normally.

The check runs symmetrically regardless of which event type arrives first — whichever case would be created **second** checks for an open case of the *other* type within the window; if found, the earlier, narrower case is the one that gets superseded, and the newer, more diagnostically specific case becomes canonical.

### 2.5 Systemic detection (implements `SystemicEvent`, Part A Section 3)

Runs as a BullMQ repeatable job, **every 60 seconds**:

- **Per-issuer check:** for each `issuer_code` seen in the trailing 10 minutes, compute failure rate and compare against a rolling baseline (default: trailing 7-day same-issuer average — simple and sufficient for demo scale; a more sophisticated same-time-of-day baseline is a reasonable upgrade once there's enough data to support it). Apply the compound threshold from Part A (`≥5× baseline AND baseline_rate≥N AND absolute_count≥M`). On breach: create `SystemicEvent(scope=ISSUER_SPECIFIC)`, transition all matching open cases to `SYSTEMIC_HOLD`, write `CaseEvent(SYSTEMIC_HOLD_APPLIED)` per case.
- **Network-wide check, same job run:** aggregate failure rate across *all* issuers for the merchant, compared against the merchant's own historical aggregate baseline. On breach: `SystemicEvent(scope=NETWORK_WIDE)`, same suppression behavior across every issuer for that merchant.
- **Resolution check, same job run:** for every active `SystemicEvent`, if failure rate has stayed below threshold for the sustain window (10 min default) → set `resolved_at`, batch re-queue affected cases to `DIAGNOSING`.

### 2.6 Checkout abandonment ingestion — the one non-Razorpay path

Unlike every other event type, `checkout.abandoned` has no Razorpay webhook to subscribe to — it requires a storefront-side signal (e.g., a JS snippet firing after N minutes of checkout-page inactivity without a completed payment).

**Decision needed (Part D item 1):** build a real, lightweight storefront SDK/pixel for this, or simulate the signal via synthetic event injection for the demo? **Proposed default: synthetic injection** — a signed internal endpoint that manually posts a `checkout.abandoned`-shaped event, exercised by the demo control panel in Module 10, in the same pattern as the Meta/Fast2SMS test-tier delivery used elsewhere. A real storefront integration is a separate build item with its own signature scheme (HMAC keyed per-merchant, same pattern as §2.2) if confirmed as needed.

### 2.7 Dispatch summary

```
Verified + deduped Event
   → (payment/subscription events) hold for buffer window (2.3)
   → still-failed after buffer? → cross-leg dedup check (2.4)
   → not superseded? → create/attach RevenueLeakCase
   → seed CardRetryBudget/UPIRetryBudget counters if payment-instrument event (same transaction as case creation, per Part A Section 3)
   → check systemic hold (2.5) — if active, set SYSTEMIC_HOLD, stop here
   → dispatch to Module 3 (Diagnosis)
```

---

## Module 3: Diagnosis Engine

**Purpose:** convert an `Event` + `RevenueLeakCase.context` into `root_cause_code`, `root_cause_label`, `diagnosis_confidence`, and — where applicable — confirm `network_directive` and emit `suggested_timing_adjustment`.

### 3.1 `root_cause_code`

The operative enum for demo purposes — Module 3 owns future refinement.

**`PAYMENT_DEGRADATION`:**
`ISSUER_SOFT_DECLINE_NSF` · `ISSUER_SOFT_DECLINE_OTHER` · `ISSUER_HARD_DECLINE_CARD_EXPIRED` · `ISSUER_HARD_DECLINE_FRAUD_SUSPECTED` (from Tier 1) · `INSTRUMENT_NOT_RECURRING_CAPABLE` (from Tier 3, shared across legs) · `GATEWAY_TIMEOUT` · `SYSTEMIC_ISSUER_OUTAGE` (state label, not a real diagnosis) · `UNKNOWN_LOW_CONFIDENCE`

**`CHECKOUT_ABANDONMENT`:**
`UPI_COLLECT_FRICTION` · `AUTH_3DS_TIMEOUT` · `NO_PAYMENT_METHOD_ATTEMPTED` · `PAYMENT_METHOD_FAILED_MIDFLOW` (should usually be caught by 2.4's merge logic instead) · `UNKNOWN_ABANDONMENT`

**`SUBSCRIPTION_FAILURE`:**
`NSF_SOFT_DECLINE` · `CARD_EXPIRED_OR_REISSUED` · `MANDATE_CANCELLED_BY_CUSTOMER` (from Tier 1 / MAC 21, or native UPI/NACH cancellation) · `INSTRUMENT_NOT_RECURRING_CAPABLE` (shared) · `UPI_AUTOPAY_CAP_EXHAUSTED` (terminal label, not really a cause) · `NACH_CLEARING_PENDING` (not yet actually failed) · `UNKNOWN_SUBSCRIPTION_FAILURE`

**`B2B_RECEIVABLE`:**
`LIQUIDITY_DELAY_LOW_RISK` · `LIQUIDITY_DELAY_HIGH_RISK` · `DISPUTE_SUSPECTED` (coarse fallback — Torque has no dispute-flagging integration) · `UNKNOWN_RECEIVABLE_RISK`

### 3.2 Diagnosis logic per leg — rule-based (Decision F's philosophy applied consistently here too, not just in Module 8)

**Payment Degradation & Subscription Failure (share the same first step):**
1. If `network_directive.tier` is already populated (set at ingestion via `MacCodeRegistry` lookup, Module 2 mechanical translation, not a diagnosis judgment) — it **takes precedence** over any decline-code guess. `TIER_1` → `ISSUER_HARD_DECLINE_FRAUD_SUSPECTED` or `MANDATE_CANCELLED_BY_CUSTOMER` (mandate context dependent), confidence `0.95`. `TIER_3` → `INSTRUMENT_NOT_RECURRING_CAPABLE`, confidence `0.95`. `TIER_2`/`TIMED` → proceed to decline-code classification below, but retain the tier for Module 5's retry-timing use.
2. Else, classify by raw `decline_code` against a lookup table (Razorpay decline code → `root_cause_code`). Known/documented codes → confidence `0.75`. Ambiguous or bank-internal opaque codes (the well-established Indian-bank decline-code-opacity problem) → confidence `0.35–0.5`, **deliberately below the `T=0.65` threshold**, correctly routing to human review by construction rather than guessing.
3. Missing `decline_code` entirely (gateway timeout, no response) → `GATEWAY_TIMEOUT`, confidence `0.5`.
4. Mandate-type-aware overrides for Leg 3: `NACH` with `clearing_cycle_status = PENDING_CLEARING` → `NACH_CLEARING_PENDING`, confidence `1.0` (this is a fact, not an inference — not actually failed yet). `UPI_AUTOPAY` with `mandate_cancelled_at` set → `UPI_AUTOPAY_CAP_EXHAUSTED`, confidence `1.0`.

**Checkout Abandonment:** classify by `(drop_stage, payment_method_attempted)` combination against a fixed lookup, confidence bands kept honestly low given the fundamental limits of inferring intent from payment-layer signals alone: `UPI_COLLECT_FRICTION` (attempted UPI Collect, dropped at VPA entry) → confidence `0.6`. `NO_PAYMENT_METHOD_ATTEMPTED` → confidence `0.4` (genuinely ambiguous — could be price, shipping cost, or just browsing; Torque has no storefront analytics to disambiguate further, as noted repeatedly in this project's own competitive analysis).

**B2B Receivable:** risk bucket from `days_overdue × Merchant_Counterparty.promise_keeping_rate` where available; confidence `0.8` if the counterparty has 3+ prior invoices on record, `0.4` for cold-start counterparties (no penalizing the diagnosis for lacking data it was never going to have — Module 8's cold-start lookup table handles the same problem on the scoring side).

### 3.3 Confidence-threshold routing (implements Decision E)

`T = 0.65`. If `diagnosis_confidence < T`, the case does **not** enter an automated playbook — it transitions directly `DIAGNOSING → ESCALATED_TO_HUMAN`, bypassing `PLAYBOOK_ACTIVE` entirely (see Part C item 1 for the state-machine update this requires).

### 3.4 `suggested_timing_adjustment` (payday-cycle heuristic)

When `root_cause_code = NSF_SOFT_DECLINE`: emit `suggested_timing_adjustment = next_month_end_working_day` as a default heuristic (no bank-side salary-date visibility exists, so "last working day of month" is a placeholder assumption, not a verified signal — Module 4 applies this only when `payday_cycle_override_enabled = true`, per Part A). This is stored as a *separate* signal from `diagnosis_confidence` — it doesn't affect how confident the diagnosis itself is, only how the retry is timed if the diagnosis is acted on.

### 3.5 Architecture note

Rule-based lookup tables for the demo, no ML model — the same "rule-based now, calibrated data collected from day one, ML later" philosophy as Module 8's Decision F, applied consistently rather than treating diagnosis and scoring as different problems requiring different levels of rigor.

---

## Module 4: Policy & Playbook Engine

**Purpose:** given a diagnosed case, select a `Playbook`, instantiate a `PlaybookRun`, and own the step-graph's authoring and validation rules (runtime traversal itself executes inside Module 5's Temporal workflow — Module 4's contract ends at "here is a valid graph and the rules for reading it").

### 4.1 Playbook catalog (demo-scope, one playbook per non-trivial `root_cause_code`)

| Leg | Playbook | Applies to |
|---|---|---|
| 1 | `PLAYBOOK_NSF_RETRY` | `ISSUER_SOFT_DECLINE_NSF` — retry with payday-cycle timing applied |
| 1 | `PLAYBOOK_GENERIC_SOFT_RETRY` | `ISSUER_SOFT_DECLINE_OTHER`, `GATEWAY_TIMEOUT` — fixed-interval retries within `CardRetryBudget` |
| 1 | `PLAYBOOK_REQUEST_NEW_INSTRUMENT` | `ISSUER_HARD_DECLINE_CARD_EXPIRED`, `INSTRUMENT_NOT_RECURRING_CAPABLE` — no retry; ask for a new payment method via WhatsApp/email + Payment Link |
| 2 | `PLAYBOOK_SUGGEST_UPI_INTENT` | `UPI_COLLECT_FRICTION` — nudge specifically suggesting Intent Flow |
| 2 | `PLAYBOOK_GENERIC_CART_NUDGE` | `NO_PAYMENT_METHOD_ATTEMPTED`, `UNKNOWN_ABANDONMENT` |
| 3 | `PLAYBOOK_SUBSCRIPTION_RETRY_CARD` | Card-mandate NSF/soft decline |
| 3 | `PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY` | UPI AutoPay soft decline — **validated ≤3 attempts at save time**, non-negotiable |
| 3 | `PLAYBOOK_SUBSCRIPTION_RETRY_NACH` | NACH soft decline — self-capped ≤3/cycle per `NACHRetryPolicy` |
| 3 | `PLAYBOOK_REQUEST_MANDATE_RENEWAL` | `MANDATE_CANCELLED_BY_CUSTOMER`, `INSTRUMENT_NOT_RECURRING_CAPABLE` |
| 4 | `PLAYBOOK_B2B_LOW_RISK_DUNNING` | `LIQUIDITY_DELAY_LOW_RISK` — gentle tone, longer intervals |
| 4 | `PLAYBOOK_B2B_HIGH_RISK_DUNNING` | `LIQUIDITY_DELAY_HIGH_RISK` — firmer tone, shorter intervals, earlier escalation |

Low-confidence cases (`diagnosis_confidence < T`) never reach this table — they route straight to `ESCALATED_TO_HUMAN` per Module 3 §3.3 / Part C.

### 4.2 Playbook validation rules (save-time, not runtime — catching a bad playbook before it can ever run is cheaper than catching it mid-execution)

- Any playbook triggered by `mandate_type = UPI_AUTOPAY` must have `stopping_rules.max_attempts ≤ 3` — **hard rejection at save time** if violated, per `UPIRetryBudget`.
- Every non-terminal node must have an `on_success` edge and at least one fallback (`on_no_response`/`on_blocked`/`on_failed`).
- No cycles in the graph — a step may never loop back to an earlier step. `stopping_rules.max_attempts`/`max_duration_days` are the only sanctioned way to bound repetition, and a graph cycle would let a playbook bypass them silently.

### 4.3 Payday-cycle application

Module 4 reads `suggested_timing_adjustment` from the diagnosis. If `payday_cycle_override_enabled = true` (merchant config, default `true`), the next node's computed fire time is the payday-adjusted target instead of the graph's static `timing_offset_hours` — implemented as a **runtime substitution at the point Module 5 computes "when does this node fire,"** not a rewrite of the stored graph. If the merchant has disabled the flag, the graph's static offset applies unmodified.

### 4.4 `multi_case_context` rendering

Each playbook step's `params` may include an optional `multi_case_template` field alongside the normal single-case `template`. When the Outreach Coordinator (Module 6, spec in Part A §5) merges two cases into one `Action`, Module 5 checks: does this step have a `multi_case_template`? If yes, render it, interpolating both cases' amounts via the `ActionCase` rows. If no, fall back to sending the higher-priority case's single-case message and **defer** the other case's outreach (never silently drop it — writes `ACTION_BLOCKED`/`OUTREACH_COORDINATOR_DEFERRED` per the existing defer policy).

---

## Module 5: Execution / Orchestration

**Purpose:** perform actions with every applicable guardrail checked immediately before firing, and the atomic `Action` + `CaseEvent` write immediately after — no exceptions to either half of that sentence.

### 5.1 Temporal workflow structure

One Temporal Workflow per `PlaybookRun` (workflow ID = `run_id` — gives exactly-once semantics and idempotent restarts for free). Workflow code must be deterministic (no direct API calls, no wall-clock reads, no randomness inside the workflow function itself — these all move into Activities):

- **`checkGuardrails(action_type, case_id)`** — Activity. Runs the check sequence in §5.2, returns `{allow, block_reason?}`.
- **`executeAction(action_type, params)`** — Activity. Calls the actual external API (Razorpay retry/mandate-execute/re-presentment, Meta WhatsApp send, Resend email, Fast2SMS send, Razorpay Payment Links create).
- **`writeActionAndEvent(...)`** — Activity. The single Postgres transaction writing `Action` + `CaseEvent` together (Part A §2.3).
- **`waitForNextStep(offset)`** — Temporal's durable timer (`workflow.sleep`). This is the concrete reason Temporal was chosen over BullMQ/Celery for this job specifically: a 30-day B2B dunning sequence's "wait" step survives process restarts, deployments, and cluster failures natively, with no separate persistence mechanism to build or maintain.

Workflow loop: read `active_step_id` → `checkGuardrails` → if blocked, write `ACTION_BLOCKED` via `writeActionAndEvent`, evaluate the graph's `on_blocked` edge → if allowed, `executeAction` → `writeActionAndEvent` with the real outcome → evaluate `on_success`/`on_no_response`/`on_failed` edge → update `active_step_id` → `waitForNextStep` until the next node's computed fire time → repeat until a terminal node, then finalize `PlaybookRun.status`.

### 5.2 Guardrail check order — concrete sequence (Part A named the entities; this is the sequence Module 5 actually runs, first-failure-wins/short-circuits)

**For any `RETRY_PAYMENT` action:**
1. `network_directive.hard_stop = true`? → block (`NETWORK_HARD_STOP` or `INSTRUMENT_NOT_RECURRING_CAPABLE`, per `hard_stop_reason`).
2. Mandate-type-aware budget check: `CARD` → `CardRetryBudget` (dual-window + hard_stop); `UPI_AUTOPAY` → `UPIRetryBudget` (attempt count **and** execution window, both required); `NACH` → `NACHRetryPolicy` (clearing-cycle status + self-imposed ceiling).
3. Subscription retries only: `PreDebitNotification` 24h-gap check. **If not satisfied, this does not just block — it auto-inserts a `SEND_PRE_DEBIT_NOTIFICATION` step ahead of the retry**, so the system self-heals toward compliance instead of dead-ending on a guardrail. Only if a fresh notification genuinely cannot be sent (e.g., no valid channel) does it fall through to `PRE_DEBIT_GAP_NOT_MET`.
4. `SYSTEMIC_HOLD` check — case under an unresolved `SystemicEvent`? → block.
5. Quiet-hours check (`allowed_hours`) — **this is a defer, not a block**: reschedule to the next allowed window per `step_timing_semantics`, don't fail the step.

**For any customer-contact action (`SEND_WHATSAPP`/`SEND_EMAIL`/`SEND_SMS`/`GENERATE_PAYMENT_LINK`):**
1. `SYSTEMIC_HOLD` check (same as above).
2. Outreach Coordinator: quiet-period-since-other-leg check (defer `OUTREACH_COORDINATOR_DEFERRED` if violated) → merge-eligibility check (route to §4.4's merge path if another case is also awaiting outreach for this counterparty).
3. Channel-specific gate: WhatsApp requires **both** `whatsapp_opt_in = true` **and** an approved `MerchantWhatsAppTemplate` for the leg — and separately, if `active_wa_conversation_expires_at > now()`, suspend the automated template entirely and route to a human agent instead (a live conversation window is not a template-sending opportunity).
4. Quiet-hours check for customer contact (a separate `allowed_hours` config from any network execution-window constraint).

### 5.3 `MacCodeRegistry` lookup — ownership and self-healing behavior

The mechanical translation (raw MAC code → tier) happens at first touch — either Module 2 at ingestion, or Module 3 at diagnosis time, whichever sees the code first — via `SELECT tier FROM MacCodeRegistry WHERE network=X AND mac_code=Y`.

**If no row is found** (an unseeded code — Part A/Part E's known gap): default to `TIER_2_CAPPED_RETRY` — the safest default, since it neither wrongly hard-stops a possibly-recoverable case nor wrongly retries past a genuine hard-stop — **and** write a `CaseEvent` flagging "unclassified MAC code encountered: `{code}`" for visibility. This turns the registry's unseeded-code gap from a passive risk into an active, self-surfacing data-collection signal: every unknown code that actually arrives gets logged automatically, giving Module 5's pre-production checklist (Decision M) a live, real list to work from instead of a cold-start guess.

### 5.4 Channel adapters (demo-scope, per Decision I)

WhatsApp → Meta Cloud API, test number + pre-verified recipients. Email → Resend API. SMS → Fast2SMS Quick SMS route, pre-verified recipients. Payment Link → Razorpay Payment Links API. Retry → Razorpay Payments API (card re-authorization), Mandate Execute API (UPI AutoPay), or NACH re-presentment API, selected by `mandate_type`.

### 5.5 BullMQ scope (ingestion only — never `PlaybookRun` execution)

BullMQ handles Module 2's inbound webhook processing and the systemic-detection repeatable job — short-lived, stateless, high-throughput work. It is never used for anything that needs to survive more than a few seconds of delay; that durability requirement is exactly why `PlaybookRun` lives in Temporal instead.

### 5.6 Postgres-polling fallback (only if Decision C resolves to "no Temporal cluster in the build window")

A `scheduled_jobs(job_id, run_id, fire_at, leg_type)` table. Two separate worker loops, not one: a **10-second-interval** poller for `leg_type = PAYMENT_DEGRADATION` (live customer-session recovery window), and a **60-second-interval** poller for the other three legs (multi-day timelines make that latency immaterial).

---

## Module 6: Compliance & Cross-Leg Guardrail Engine

**Purpose:** the canonical, callable home for every guardrail check Module 5 needs, plus the two things that don't fit cleanly inside a single `Action` check: escalation-ceiling handling and human-queue routing.

### 6.1 Relationship to the Outreach Coordinator

The Outreach Coordinator (priority formula, quiet period, merge policy, defer policy, open-conversation policy) is fully specified in **Part A §5** and operationally owned by this module — not re-specified here, only referenced.

### 6.2 `GuardrailEngine` — a single interface, not scattered inline checks

Module 5's Temporal Activities call one function: `GuardrailEngine.check(action_type, case_id, params) → { allow: bool, block_reason?: BlockReason }`, which internally runs the ordered sequence from Module 5 §5.2. This is an explicit ownership boundary worth naming: **Module 5 executes actions and owns the atomic write; Module 6 owns the decision of whether an action is allowed to happen at all.** Without this separation, guardrail logic tends to get duplicated or drift between whichever engineer touches Module 5 next and whichever touches Module 6 next.

### 6.3 Escalation-ceiling enforcement

When a `PlaybookRun` reaches `stopping_rules.escalation_ceiling` without resolution, Module 6 — not Module 5 — is what transitions the case to `ESCALATED_TO_HUMAN` and writes the corresponding `CaseEvent`. This keeps "when do we give up on automation" as a compliance/policy decision rather than an execution-layer side effect.

### 6.4 Human queue

A simple FIFO-per-merchant queue keyed on `case_id`, populated from three independent sources that all land in the same place: low-confidence diagnoses (Module 3 §3.3), escalation-ceiling cases (§6.3), and `PromiseToPay.on_broken` (Part A, confirmed behavior — routes to human, never a harsher bot message). Each entry carries a `reason` and a `priority` (reused directly from Module 8's `(probability × amount) ÷ cost` score) so a human agent's queue is sorted by the same economic logic as everything else in the system, not a separate ad hoc ranking.

---

## Module 7: Payment Reconciliation & Attribution

**Purpose:** match incoming payment success signals to open cases, decide who gets credit for the recovery, and close cases correctly.

### 7.1 Matching logic

On `payment.captured`, `subscription.charged`, or `payment_link.paid`/`.partially_paid`:

1. **Direct match via `PaymentLink`.** Does the payment reference a `link_id` Torque generated? → `recovery_type = AGENT_ASSISTED`, attribute fully to `PaymentLink.case_id`, `credit_weight = 1.0`. This is the cleanest signal in the system — Part A already flags it as the single most important attribution mechanism, and it's why the `PaymentLink` entity exists at all.
2. **Indirect match** (customer paid directly via their own bank/UPI app, no Torque-generated link involved). Match by `(merchant_id, counterparty_id, amount)` against open cases. Exactly one match → attribute to it, then decide `AGENT_ASSISTED` vs. `SELF_RECOVERED` by a time-based heuristic: a Torque `Action` executed for this case within the preceding **24 hours** (default, tunable) → `AGENT_ASSISTED`; no Torque action in that window → `SELF_RECOVERED`.
3. **Multiple open cases match simultaneously** (the merged-outreach scenario from the Outreach Coordinator). Split `credit_weight` proportional to each case's `amount_at_risk` relative to the combined total, respecting the `ActionCase` sum-to-1 constraint (Part A §3, enforced, not just documented).
4. **No case matches at all** — payment arrived before Torque finished diagnosing, or the case is still in `DETECTED`/`DIAGNOSING`. Close as `CANCELLED`, `recovery_type = SELF_RECOVERED`.

### 7.2 Case closure

Full amount matched → `RECOVERED`, `recovered_amount = amount_at_risk`, `closed_at = now()`. Partial amount (B2B specifically) → `PARTIALLY_RECOVERED`, case stays open, matching `B2BInvoice.outstanding_amount` decremented by the payment amount.

### 7.3 Timing

Module 7 is a consumer of already-verified `Event` rows from Module 2's pipeline — it does not run its own separate webhook ingestion path. Payment-success events go through the exact same signature verification (Part A §2.5) as every other inbound signal before Module 7 ever sees them.

---

## Module 8: Recovery Scoring Model

**Purpose:** compute `(probability × amount_at_risk) ÷ cost` for every open case — the number that feeds both the Outreach Coordinator's priority ordering (Part A §5) and the merchant dashboard's "top at-risk cases" view (Module 9).

### 8.1 Cold-start lookup — the operative algorithm behind Decision F

`probability = lookup(leg_type, amount_bucket, days_since_failure)`, using the exact benchmark table already locked in Part A's Decision F (Subscription 0–48h → 65%, etc.). Module 8's job is implementing this as a **live, queryable function**, then layering a warm-start adjustment where relationship history exists: multiply the base lookup probability by a normalized `Merchant_Counterparty.promise_keeping_rate` factor, **capped at 0.5×–1.3×** of the base rate. Capping (rather than fully replacing the cold-start number with a raw history-derived one) keeps cold-start and warm-start cases on a comparable scale, so the priority ordering doesn't swing wildly just because one case happens to have relationship history and its neighbor doesn't.

### 8.2 Cost sourcing

`cost` for a case = the sum of `ChannelRateCard.rate_per_unit` for whichever channel(s) the assigned playbook's **next likely step** would use — a forward-looking prioritization input, explicitly not a backward-looking spend total (that's a Module 9 reporting concern, computed separately).

### 8.3 Recompute cadence

Recomputed on: case creation, diagnosis completion (probability may shift once `root_cause_code`/`diagnosis_confidence` are known), and once daily for all open cases (the `days_since_failure` bucket shifts over time even with no other change to the case).

### 8.4 Upgrade path — feature set named now even though the model itself is roadmap

Unchanged from Decision F: XGBoost + SHAP with T-learner/X-learner meta-learners once 500+ resolved cases exist. The feature set that future model would train on: `leg_type`, `root_cause_code`, `diagnosis_confidence`, `amount_at_risk`, `days_since_failure`, `Merchant_Counterparty.promise_keeping_rate`, `Merchant_Counterparty.risk_score`, `network_directive.tier` (where applicable), `mandate_type` (where applicable). Naming this now confirms that Part A's fields were already designed to be feature-store-ready — no schema change needed when the upgrade eventually happens, only a new consumer of data that's been collected since day one.

---

## Module 9: Reporting & Measurement

**Purpose:** the surface that proves the five differentiators are real, to both the merchant and the judges — not asserted, demonstrated.

### 9.1 Dashboard metrics

| Metric | Computation |
|---|---|
| ₹ recovered by leg | `SUM(recovered_amount) WHERE recovery_type != SELF_RECOVERED`, grouped by `leg_type` |
| Recovery rate by leg | recovered cases ÷ total cases, per `leg_type` |
| Incrementality lift | treatment recovery rate − control recovery rate, with a **Wilson score confidence interval** (appropriate for small-sample honesty — a naive normal-approximation interval can produce nonsensical bounds at demo-scale sample sizes) |
| SUTVA-adjusted lift | the same lift calculation excluding any control-cohort counterparty that also appears in a treatment cohort for another merchant in the same window (Part A §6) — shown **alongside**, not instead of, the headline number |
| Exception list | every `Action` with `outcome = BLOCKED_BY_GUARDRAIL`, grouped by `block_reason` — this is the compliance-by-construction differentiator made visible, and should be surfaced prominently, not buried under the revenue numbers |
| Cost efficiency | total `Action.cost` vs. total `recovered_amount` — a direct ROI figure |

### 9.2 Explainability panel

A direct, mechanical rendering of the `CaseEvent` stream for a single case, in `event_seq_id` order, using `reasoning` as the primary human-readable text and `payload` for structured detail. **No separate computation is needed** — this is the payoff of consolidating all history into one stream back in Part A: the "why did the agent do this" view is a query, not a feature to build.

### 9.3 Demo narrative note

Showing the SUTVA caveat openly, rather than hiding it, is itself part of the "we report honestly, not just favorably" differentiator — carried into Module 13's script as a deliberate beat, not an afterthought to mention if asked.

---

## Module 10: UI/UX

Lighter treatment than Modules 1–9 — this layer is less architecturally load-bearing and more dependent on team/design preference, but still concrete enough to build against.

- **Merchant Dashboard:** Module 9's metrics, a filterable case list (by leg/status), the exception list surfaced near the top.
- **Agent Console:** case detail view = the explainability panel (§9.2) plus manual override controls (pause / cancel / resolve) for anything sitting in the human queue (Module 6 §6.4).
- **Demo Surface:** a "live feed" view showing cases moving through states in real time — visually demonstrates the agent working during a judged demo — plus a control panel to inject synthetic events on demand, which is also where Module 2 §2.6's synthetic checkout-abandonment injector and Module 5 §5.4's Decision-K demo scenarios (hard-stop MAC, UPI cap, NACH ceiling) live as one-click triggers rather than requiring live production traffic to exercise.

---

## Module 11: Tech Stack & Infra

Consolidating what was otherwise scattered across the Decisions table into one concrete list:

| Layer | Choice | Source |
|---|---|---|
| Database | Postgres | Decision B |
| Workflow orchestration | Temporal (OSS, self-hosted) for `PlaybookRun`; Postgres-polling fallback if infeasible | Decision C |
| Queue | BullMQ + Redis, ingestion only | Decision C |
| WhatsApp | Meta Cloud API, developer test tier | Decision I |
| Email | Resend, free tier | Decision I |
| SMS | Fast2SMS, Quick SMS test route (demo only) | Decision I |
| Payments / Payment Links / retries / webhooks | Razorpay APIs | — |
| Schema validation | Pydantic (Python) or Zod (TypeScript) at the ORM boundary | Part A §3, cross-cutting |

**Decision needed (Part D item 2):** the backend language/framework was never chosen anywhere across this project. It matters here specifically because it cascades into two already-locked architectural choices: Temporal's SDK (first-class support exists for Go, Java, Python, and TypeScript — pick based on team familiarity) and which schema-validation library enforces the typed `context` models and `CaseEvent.payload` schemas (Pydantic if Python, Zod if TypeScript). Nothing else in this document depends on the choice, but these two things do, so it can't stay implicit any further into implementation.

---

## Module 12: Build Roadmap

**Decision needed (Part D item 3): total build window length.** A day-by-day plan can't be written without knowing how many days are available. What follows is phase-based rather than calendar-dated so it can be converted the moment the window length is known.

| Phase | Contents | Rationale for ordering |
|---|---|---|
| **1 — Foundation** | Part A schema migration; webhook ingestion skeleton + signature verification (Module 2 §2.2); Temporal/BullMQ setup; seed `MacCodeRegistry` + `ChannelRateCard` | Nothing else can be tested without these existing first |
| **2 — Core loop, Leg 1 only** | Diagnosis (Leg 1 rules), 2–3 playbooks, execution (retry + WhatsApp), reconciliation — end to end for **one leg** before touching the others | Proves the shared-engine architecture actually works on a real path before betting the remaining time on it working the same way four times |
| **3 — Widen to all four legs** | Replicate Phase 2's proven pattern into Legs 2/3/4 configs | This is the payoff of the shared-engine design — should be materially faster than Leg 1 was, since the hard architectural problems are already solved |
| **4 — Compliance hardening** | `CardRetryBudget`/`UPIRetryBudget`/`NACHRetryPolicy` enforcement, Outreach Coordinator, systemic detection | These are what make the "compliance-by-construction" differentiator real rather than asserted — needs to exist before the demo, not be bolted on after |
| **5 — Reporting + demo polish** | Dashboard, explainability panel, incrementality calculation, synthetic demo data + injector, dry run of Module 13's script | Last, because it depends on everything above already producing real `CaseEvent`/`Action` data to report on |

---

## Module 13: Demo Script / Judging Narrative

Built around the five locked differentiators (Part A §0), structured as a narrative arc. **Decision needed (Part D item 4):** if there's a published judging rubric with weighted categories, share it — the ordering and emphasis below should follow the rubric's actual weights rather than this document's best guess at what matters.

1. **Open** with the fragmentation problem — a merchant today stitches together 3–4 vendors for this, four logins, four "recovered revenue" definitions. (~30 seconds)
2. **Live:** inject a payment failure, show diagnosis running — the MAC tier lookup, the decline-code classification, the confidence score attached to it. This is the "why," not just the "what," and it's the root-cause-diagnosis differentiator made concrete.
3. **Live:** show a guardrail actually blocking an action — a Tier 1 hard-stop MAC preventing a retry, or a UPI AutoPay case hitting its cap. Compliance-by-construction, visible in the exception list, not just claimed in the pitch deck.
4. **Live:** a B2B multi-invoice bundle, and a merged cross-leg outreach event (§4.4's `multi_case_context` in action) — the "one ledger" differentiator, shown rather than described.
5. **Dashboard:** incrementality lift with its honest confidence interval and the SUTVA footnote shown openly (Module 9 §9.3) — "we measure lift, not vanity totals, and we're transparent about the limits of our own measurement."
6. **Close** with the cost-efficiency number and the exception list as evidence of restraint — the system is being shown *not* doing things it isn't allowed to do, which is a harder and more credible thing to demonstrate than a system doing a lot of things.

---

# PART C — Corrections and Additions to Module 1

1. **New state-machine edge:** `DIAGNOSING → ESCALATED_TO_HUMAN`, direct, bypassing `PLAYBOOK_ACTIVE` entirely, for cases whose `diagnosis_confidence` falls below `T = 0.65` (Module 3 §3.3). Update the state-machine diagram in Part A §4 to include this edge alongside the existing `escalation_ceiling` path.
2. **`GuardrailEngine` as a named interface** (Module 6 §6.2): the calling convention Module 5 uses to consult the guardrail entities (`CardRetryBudget`, `UPIRetryBudget`, etc.) — one function, one return shape, owned by Module 6.
3. **Checkout abandonment's ingestion mechanism** (Module 2 §2.6): there is no Razorpay webhook for this signal — it requires a separate storefront-side path, given a proposed demo-scope default (synthetic injection).
4. **`root_cause_code` enum** is now defined in Module 3 §3.1.

---

# PART D — Decisions Needed From You

Everything else in this document proceeds on a stated default. These four need your input:

| # | Decision | Where it matters | What's blocked without it |
|---|---|---|---|
| 1 | **Checkout abandonment ingestion:** build a real storefront SDK/pixel, or simulate via synthetic event injection for the demo? | Module 2 §2.6 | Proposed default (synthetic injection) is in place — a real storefront integration is a separate build item with its own signature scheme, not currently in any phase of Module 12's roadmap. |
| 2 | **Backend language/framework.** | Module 11 | Cascades into the Temporal SDK choice and the Pydantic-vs-Zod validation layer. Every other tech choice in Module 11 is settled; this one isn't. |
| 3 | **Total build window length** (how long is "the hackathon clock"?). | Module 12 | The roadmap is phase-based specifically because this was never stated. Give me a number of days and I'll convert Phases 1–5 into a calendar-dated plan. |
| 4 | **Judging rubric, if one exists with published weighted categories.** | Module 13 | The demo script's ordering/emphasis is my best construction from the five locked differentiators — a real rubric should override my guess at what matters most. |

Two secondary items (Temporal go/no-go, Tier 1/Tier 3 precedence) don't block anything downstream since working defaults are already in place — tracked in Part E instead.

---

# PART E — Known Open Items (system-wide)

1. **`MacCodeRegistry` unseeded codes.** Only `03, 21, 5C, 9G, 40, 41, 24–30` are seeded with verified tiers. A large remaining set (`01, 02, 04, 05, 07, 19, 22, 39, 42, 43, 51, 52, 53, 57, 59, 61, 62, 65, 75, 78, 79, 82, 83, 86, 91, 93, 96`, plus all Visa equivalents) is not yet classified — do not assume hard-stop status for any of them without validating against Razorpay's actual acquirer output. Module 5 §5.3 makes this self-surfacing: any unseeded code encountered in production writes a flagged `CaseEvent`, turning this into a live, growing checklist rather than a cold-start guess.
2. **Tier 1 vs. Tier 3 precedence** when a single case receives codes from both tiers across different attempts. Default in use: `TIER_1_HARD_STOP > TIER_3_INSTRUMENT_DEAD` (Part A §4) — not yet independently confirmed.
3. **`CaseEvent.STEP_TRANSITIONED` payload shape** (`{ from_step_id, to_step_id, edge_condition, outcome }`) is a proposed default, not yet confirmed.
4. **NACH cross-instrument aggregation** (combining cheque and NACH dishonours on the same account) — 🔮 roadmap, requires bank-side visibility Torque doesn't have.
5. **SMS production path** — TRAI DLT registration — 🔮 roadmap, not built.
6. **Card Account Updater (CAU)** — 🔮 roadmap, no free tier exists, excluded from the build entirely.
7. **DPDP erasure-request intake flow** — 📋 design-only, schema supports it, flow itself not built for demo.
8. **Decision C's Temporal vs. Postgres-polling fallback** — go/no-go depends on team comfort standing up a self-hosted cluster in the build window; a working fallback is already specified either way.
9. **Module 2 §2.3's buffer windows** (90s for payment failures, 30s for subscription failures) — stated defaults, not empirically derived.
10. **Module 2 §2.4's cross-leg dedup window** (2 hours) — stated default, same caveat.
11. **Module 7 §7.1's `AGENT_ASSISTED` vs. `SELF_RECOVERED` attribution window** (24 hours) — stated default, same caveat.
12. **Module 8 §8.1's warm-start cap** (0.5×–1.3× the cold-start probability) — stated default, not derived from any historical Torque data.
13. **Module 12's roadmap has no calendar dates** — pending Part D item 3.
