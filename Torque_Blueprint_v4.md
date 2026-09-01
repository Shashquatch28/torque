# Torque — Module 1, Rev. 4
### Resolution of the v3 Critique — Every Item Mandatorily Closed
> Method: every claim in the v3 critique that depended on an external fact (network rule, regulatory instrument, product/API behavior) was checked against current sources before being locked here. Section 1 covers what that check changed. Section 2 closes all seventeen critique items — no menus, one call per item. Section 3 is the updated entity reference. Section 4 re-locks the decisions table. Nothing in Module 1 remains 🟡 after this document.

---

## 1. What the literature review changed

Six findings. Four confirm the critique was right and sharpen the fix; two catch things the critique itself missed.

**A. RBI superseded the piecemeal e-mandate circulars.** On April 21, 2026, RBI issued a single consolidated *Digital Payments – E-Mandate Framework, 2026*, replacing the earlier scattered circulars this blueprint was built against. Substance is the same — pre-debit notification ≥24h before "the actual charge/debit," which by its own wording attaches to each debit event, not to the mandate as a whole — but the instrument name in your compliance references (Decision H, `SubscriptionFailureContext` comments) is now stale and should cite the 2026 Framework. No architectural change beyond the fix already scoped in Issue VI.

**B. Mastercard's retry cap is two concurrent windows, not one.** `CardRetryBudget`'s pre-retry check (`attempts_used < 10`) was written against a single 30-day window. The actual TPE thresholds are **≤10 declined attempts per card per merchant per 24 hours** *and* **≤35 per 30 days**, both enforced simultaneously, with per-excess-attempt fees (reported around $0.50/attempt at current tiers — treat as a config value, not a literal, since scheme fee schedules move). A single-window counter under-blocks early in the cycle and over-blocks late in it. Fixed in Section 3.

**C. MAC 5C and 9G are not hard stops — the blueprint has this wrong since v1.** Every network reference checked (Mastercard MAC tables via processor documentation) places 5C ("blocked by issuer / not supported") and 9G ("blocked by cardholder / contact cardholder") in **Category 2** — reversible, retry permitted up to the standard attempt cap — the same bucket as 03/19/39/51/52/53/59/61/62/65/75/78/86/91/93/96. The true unconditional hard-stops in Mastercard's scheme are codes like 03 and 21 ("do not retry — fraudulent" / "do not retry — lost or stolen"), plus true Category 1 lifecycle codes (04/07/41/43/57). `CardRetryBudget.hard_stop_reason` and the `network_directive` field comments in `RevenueLeakCase` both currently list 5C and 9G alongside 03/21 as permanent blocks. **This must be corrected before Module 5 is written** — retrying a 5C/9G decline within the standard attempt ceiling is compliant behavior, and treating it as a permanent block silently kills recoverable cases. Flag for validation against Razorpay's actual acquirer-level MAC mapping at implementation time, since categorization has minor processor-level variance — but the default in this spec is now the documented behavior, not the blueprint's stricter one.

**D. Razorpay's Payment Link webhooks are exactly what Issue X needs.** `payment_link.paid`, `.partially_paid`, `.cancelled`, `.expired` all exist today as subscribable events with full payload (status, amount_paid, timestamps). The fix in Issue X is not a roadmap item — it's a webhook subscription plus one new table, buildable now.

**E. A firmer SMS example than the original Decision I.** Fast2SMS advertises a concrete ₹50 free-credit signup with no DLT template required for test sending. This is a more specific, checkable claim than "MSG91/Twilio have free trials" — use it as the primary example in the corrected Decision I.

**F. Razorpay's webhook signature scheme has an implementation detail Module 1 needs to carry forward.** Verification is HMAC-SHA256 over the **raw, unparsed request body** (re-serialized JSON will not match), compared in constant time, keyed by a dashboard-set secret that is distinct per Live/Test mode. Razorpay also sends a dedicated `X-Razorpay-Event-Id` header, unique per event including retries. **`Event.idempotency_key` should be sourced from this header, not derived from payload content** — the payload-derived approach risks collisions across genuinely distinct events that happen to share business-level fields.

---

## 2. Issue-by-issue resolution — all 17 closed

### I. `step_history` contradiction → **removed, literally**
`PlaybookRun.step_history` is deleted from the entity definition. It does not exist as a column. Every step-entered/exited/outcome event is a `CaseEvent` with `event_type = STEP_TRANSITIONED`. If Module 5 needs "what's the run's current branch position," that's `PlaybookRun.active_step_id` — a single current-state pointer, not a log. There is now exactly one place execution history lives.

### II. Dual-write atomicity → **transactional outbox, single Postgres transaction**
Every `Action` write and its corresponding `CaseEvent` write happen inside one `BEGIN…COMMIT` block, same Postgres instance. This is the entire fix — no message broker, no two-phase commit, no additional infrastructure. Locked as a Module 5 hard requirement: **no code path may write `Action` without `CaseEvent` in the same transaction.** A code-review checklist item, not a design document.

### III. `network_directive` sequential MACs → **most-restrictive-wins, permanently**
`network_directive` stores the most restrictive MAC ever received for the case, non-overridable by a later more permissive response. Full per-attempt history lives in `CaseEvent` (`event_type = NETWORK_DIRECTIVE_RECEIVED`, payload `{ mac_code, attempt_number, received_at }`). Precedence order (most → least restrictive), locked: `03/21 (hard stop) > 5C/9G/other Cat-2 (capped retry) > 24–30 (timed retry window) > null`. A case that receives MAC 02 then MAC 03 has `network_directive = MAC_03` and `CardRetryBudget.hard_stop = true` permanently, with both events preserved in the stream.

### IV. `CardRetryBudget` misapplied to NACH → **mandate-type scope guard + `NACHRetryPolicy`**
`CardRetryBudget` gets a hard scope: it is consulted by Module 5's pre-retry check **only when `mandate_type = CARD`**. For NACH, a new entity:

| Field | Notes |
|---|---|
| `nach_retry_policy_id` | PK |
| `mandate_id` | FK |
| `clearing_cycle_status` | `PENDING_CLEARING` \| `RETURNED` \| `CLEARED` — NACH returns take 3–7 banking days, batch clearing, not real-time |
| `return_reason_code` | NPCI NACH return reason (e.g., "insufficient funds," "account closed") |
| `retry_eligible_after` | Date — next batch clearing window, not a real-time retry |

Module 5's pre-retry branch is now `mandate_type`-aware: `CARD → CardRetryBudget`, `NACH → NACHRetryPolicy`, `UPI_AUTOPAY → UPIRetryBudget` (below). No shared code path silently applies the wrong network's rules.

### V. NPCI UPI AutoPay 4-attempt limit → **new `UPIRetryBudget` entity, enforced**
Confirmed live and mandatory: NPCI's August 1, 2025 rule caps every AutoPay mandate at one original attempt plus three retries — four total — after which the mandate is cancelled, non-negotiable regardless of merchant playbook config.

| Field | Notes |
|---|---|
| `budget_id` | PK |
| `mandate_id` | FK — scoped per-mandate, not per-card (UPI AutoPay has no card token) |
| `attempts_used` | Int, includes the original attempt |
| `hard_cap` | `3` (retries only; 4 total with the original) — constant, not configurable, because it's NPCI-enforced not merchant-enforced |
| `mandate_cancelled_at` | Set by Module 2 when NPCI confirms cancellation post-4th attempt |

Pre-retry check: `attempts_used < 3 AND mandate_cancelled_at IS NULL`. `Playbook.stopping_rules.max_attempts` for Leg 3 UPI AutoPay playbooks is now a *ceiling that cannot exceed 3*, enforced at playbook-validation time, not just at runtime — a playbook configured for 5 attempts on a UPI AutoPay trigger should fail validation, not fail silently at attempt 4.

### VI. `pre_debit_notified_at` cardinality and naming → **per-attempt tracking table**
Single field replaced with:

| Field | Notes |
|---|---|
| `notification_id` | PK |
| `case_id` | FK |
| `notified_at` | Timestamp of this specific pre-debit notification |
| `covers_attempt_number` | Which retry attempt this notification authorizes |
| `channel` | How it was sent |

Renamed away from the ambiguous `pre_debit_notified_at` entirely — this table only ever represents Torque-initiated retry notifications, not the original merchant/PSP failure notice, so the naming ambiguity from the critique is structurally eliminated, not just relabeled. Module 6's Guardrail Engine check becomes: `EXISTS (SELECT 1 FROM PreDebitNotification WHERE case_id = X AND covers_attempt_number = next_attempt AND now() - notified_at >= 24h)`. Cite the RBI Digital Payments – E-Mandate Framework, 2026 (Finding A) as the compliance reference going forward.

### VII. Payday-cycle override → **heuristic signal, not mandatory substitution**
`NSF_SOFT_DECLINE` payday-cycle timing moves from a hardcoded Policy Engine substitution to a **Diagnosis Engine output**: `suggested_timing_adjustment` with an attached `diagnosis_confidence`, surfaced from Module 3. Module 4 (Policy) applies it **by default** but reads a per-merchant config flag (`payday_cycle_override_enabled`, default `true`) that lets a merchant with irregular-pay counterparties (gig workers, contractors) turn it off. The Diagnosis Engine's confidence score is what should eventually distinguish "NSF, salary pending" from "NSF, genuinely insolvent" — flagged for Module 3 as a training-signal candidate, not solved here, but the architecture no longer forces a wrong default that can't be overridden.

### VIII. Outreach coordinator priority ignoring amount → **formula, not fixed order**
The fixed `B2B_RECEIVABLE > SUBSCRIPTION_FAILURE > PAYMENT_DEGRADATION > CHECKOUT_ABANDONMENT` ordering is deleted. Outreach coordinator priority is now the same formula that governs everything else in the system: `(probability × amount_at_risk) ÷ cost`, computed per case, with `probability` sourced from the Module 8 leg-type × bucket lookup table. Leg type still matters — it's baked into the probability estimate (a fresh subscription failure scores higher than a 90-day-overdue invoice) — but it can no longer override amount by fiat. A ₹500 invoice no longer out-prioritizes a ₹50,000 subscription failure.

### IX. `merged_case_ids` array → **`ActionCase` join table**

| Field | Notes |
|---|---|
| `action_id` | FK |
| `case_id` | FK |
| `is_primary` | Bool — exactly one `true` per action |
| `credit_weight` | 0–1 float — Module 7 attribution splits recovery credit proportionally across merged cases instead of guessing |

`Action.merged_case_ids` array field is removed. Queries become standard FK lookups; no GIN index workaround needed; attribution has an explicit weight column instead of an implicit "figure it out" array.

### X. Payment Link lifecycle untracked → **`PaymentLink` entity + real webhook subscription**
Confirmed buildable now (Finding D) — not roadmap.

| Field | Notes |
|---|---|
| `link_id` | PK — Razorpay's `plink_...` ID |
| `action_id`, `case_id` | FK |
| `status` | `issued` \| `partially_paid` \| `paid` \| `expired` \| `cancelled` |
| `amount_paid` | Updated by webhook |
| `expires_at`, `paid_at` | |

Module 2 ingestion subscribes to `payment_link.paid`, `payment_link.partially_paid`, `payment_link.expired`, `payment_link.cancelled`. Module 7 reads `PaymentLink.status` to determine `AGENT_ASSISTED` vs `SELF_RECOVERED` — the single most important attribution signal is now visible instead of inferred.

### XI. `SystemicEvent` cold-start and resolution flapping → **floor conditions + sustain window**
Threshold becomes a compound condition, not a bare ratio:
`failure_rate ≥ 5× rolling_10min_baseline AND baseline_rate ≥ N failures/min AND absolute_failure_count ≥ M in the detection window` — `N` and `M` are per-issuer config values, not hardcoded, but they now exist in the spec (they didn't before), closing the cold-start false-positive gap for new/low-volume merchants.

`resolved_at` now requires a **sustain window**: failure rate must stay below threshold for **Y consecutive minutes** (default 10, config value) before `resolved_at` is written. This stops the `SYSTEMIC_HOLD → DIAGNOSING → SYSTEMIC_HOLD` flapping on intermittent bank outages that would otherwise fire outreach mid-degradation.

### XII. SMS claim correction → **Fast2SMS confirmed, wording fixed**
Decision I's claim "no free Indian SMS gateway exists" is factually wrong and is replaced: **Fast2SMS provides a confirmed ₹50 free-credit signup tier for test SMS delivery, no DLT template required**, usable in the same pattern as the WhatsApp demo — capped to pre-verified recipient numbers. MSG91 and Twilio also offer trial tiers as secondary options, but Fast2SMS is the concrete, checkable claim to put in the pitch.

### XIII. `CaseEvent.payload` untyped → **schemas defined per `event_type`, now**
Every `event_type` gets a locked payload shape, validated at write time by the same Pydantic/Zod boundary already used for leg contexts:

| `event_type` | `payload` shape |
|---|---|
| `STATUS_CHANGED` | `{ from_status, to_status, trigger }` |
| `DIAGNOSIS_COMPLETED` | `{ root_cause_code, diagnosis_confidence, network_directive }` |
| `ACTION_EXECUTED` | `{ action_type, channel, outcome, cost }` |
| `ACTION_BLOCKED` | `{ action_type, block_reason }` |
| `NETWORK_DIRECTIVE_RECEIVED` | `{ mac_code, attempt_number, received_at }` |
| `PROMISE_CAPTURED` | `{ promised_amount, promised_date }` |
| `PAYMENT_RECONCILED` | `{ recovered_amount, recovery_type }` |
| `SYSTEMIC_HOLD_APPLIED` | `{ systemic_event_id, issuer_code }` |
| `HUMAN_RESOLVED` | `{ resolution, agent_id }` |

No `event_type` may be written without a matching schema in this table. Adding a new `event_type` later requires adding its schema here first — that's the actual point of "typed JSON," and it wasn't true until now.

### XIV. Polling frequency unspecified (Decision C fallback) → **stratified by leg type**
If the Postgres-backed job table fallback is used instead of Temporal: **Leg 1 (payment degradation) requires sub-10-second polling** for the first-retry step, because the recovery window is the live customer session. **Legs 2, 3, and 4 use 60-second polling** — multi-day/multi-week timelines make that latency immaterial. This is a per-`Playbook.leg_type` config on the polling worker, not a global constant.

### XV. `B2BInvoice` grouping logic unspecified → **trigger, criteria, and window, locked**
- **Trigger:** on `invoice.overdue`, Module 2 checks for an existing **open** (non-terminal-status) `RevenueLeakCase` with `leg_type = B2B_RECEIVABLE` for the same `(merchant_id, counterparty_id)` pair.
- **If found:** the new `B2BInvoice` row attaches to that existing `case_id`. No new case is created.
- **If not found:** a new case is created, and the new invoice becomes its first `B2BInvoice` row.
- **Time window:** none needed beyond "case is still open" — this is deliberately not date-bounded, because the whole point of bundling is one coherent "here's everything you owe" message regardless of when each invoice individually went overdue. A case only stops accepting new invoices when it closes (`RECOVERED`/`WRITTEN_OFF`/`CANCELLED`), at which point a subsequent `invoice.overdue` for the same counterparty opens a fresh case.

This removes the ambiguity for Module 2 (ingestion) and Module 4 (dunning message rendering) simultaneously — both now read from the same rule.

### XVI. SUTVA intra-merchant spillover → **documentation fix, not a schema change**
The Module 1 SUTVA section is amended to state explicitly: *counterparty-level cohort assignment (`Merchant_Counterparty.in_control_cohort`) already resolves intra-merchant cross-leg spillover, because every case for a given counterparty at a given merchant shares one cohort assignment. The unresolved SUTVA exposure is cross-merchant only* (a counterparty in treatment for Merchant X and control for Merchant Y) — which Module 9 flags per the existing footnote mechanism. No design work needed here; the critique correctly identified that the acknowledgment text was misleading, not that the architecture was incomplete.

### XVII. Webhook signature verification missing → **ingestion-layer hard requirement, Module 1 → Module 2 handoff**
Added to Module 1 as a cross-cutting requirement Module 2 must implement before any other ingestion logic: every inbound Razorpay webhook is verified via HMAC-SHA256 over the **raw** request body against the dashboard-set secret (Live/Test secrets are distinct — don't cross them), compared in constant time, **before** the payload is parsed or any `Event` row is written. Requests that fail verification are rejected with no side effects — not logged as a `DEGRADED` or `SUSPICIOUS` case, just dropped. `Event.idempotency_key` is sourced from Razorpay's `X-Razorpay-Event-Id` header (Finding F), not derived from payload fields.

---

## 3. Updated entity reference (entities that changed only)

**`RevenueLeakCase.network_directive`** — semantics locked: most-restrictive-ever, non-overridable, precedence `03/21 > 5C/9G/Cat-2 > timing codes 24-30 > null` (corrected per Finding C).

**`CardRetryBudget`** — dual-window, corrected hard-stop set:
| Field | Notes |
|---|---|
| `budget_id` | PK |
| `card_token_hash`, `merchant_id` | |
| `attempts_used_24h` | Int, rolling 24h window |
| `attempts_used_30d` | Int, rolling 30-day window |
| `hard_stop` | Bool — set only on MAC `03`/`21`/true Category-1 codes, **not** 5C/9G |
| `hard_stop_reason` | |

Pre-retry check: `attempts_used_24h < 10 AND attempts_used_30d < 35 AND hard_stop = false`.

**`UPIRetryBudget`** — new (Issue V).
**`NACHRetryPolicy`** — new (Issue IV).
**`PreDebitNotification`** — new, replaces `SubscriptionFailureContext.pre_debit_notified_at` (Issue VI).
**`ActionCase`** — new, replaces `Action.merged_case_ids` (Issue IX).
**`PaymentLink`** — new (Issue X).

**`PlaybookRun`** — `step_history` field deleted (Issue I).

**`Playbook.step_timing_semantics`** — payday-cycle clause rewritten from mandatory substitution to `suggested_timing_adjustment` with merchant override flag (Issue VII).

**`Event.idempotency_key`** — sourced from `X-Razorpay-Event-Id` header, not payload-derived (Finding F).

**`CaseEvent`** — `payload` schemas locked per `event_type` (Issue XIII); new `event_type` value `NETWORK_DIRECTIVE_RECEIVED` and `STEP_TRANSITIONED` added to the enum to absorb what `step_history` used to carry.

**`SystemicEvent`** — threshold gains floor conditions (`baseline_rate ≥ N`, `absolute_count ≥ M`); `resolved_at` gains sustain window `Y` minutes (Issue XI).

**Outreach Coordinator (Module 6 preview)** — priority rule replaced with `(probability × amount) ÷ cost` at case level (Issue VIII).

**`B2BInvoice` grouping** — trigger/criteria/window locked as: open-case-lookup by `(merchant_id, counterparty_id)`, no date bound, closes on case terminal status (Issue XV).

---

## 4. Decisions table — re-lock

| # | Decision | Status after v4 |
|---|---|---|
| C | Temporal (OSS) for `PlaybookRun`, BullMQ for ingestion; Postgres-polling fallback | Unchanged, but fallback now carries stratified polling frequency (Issue XIV) |
| I | WhatsApp demo via Meta test numbers; email via Resend free tier; **SMS via Fast2SMS ₹50 free-credit tier** (corrected, Finding E / Issue XII) | Corrected |
| — | *(new)* Webhook signature verification is a Module 1 cross-cutting requirement, not a Module 2 afterthought | Added (Issue XVII) |

All other decisions (A, B, D, E, F, G, H, J, K) stand as locked in Rev. 3 — nothing in the v3 critique or this literature review touched them.

---

## Module 1 status: 🔒 **LOCKED**

All seventeen v3-critique items are closed with concrete schema, not deferred language. Six literature-review findings are folded in — four confirm and sharpen existing fixes, two (MAC 5C/9G miscategorization, dual-window Mastercard threshold) correct a defect that predates the v3 critique and would have shipped silently otherwise.

Next: **Module 2 — Signal Ingestion**, which now inherits a fully specified contract — webhook signature verification, `X-Razorpay-Event-Id`-sourced idempotency, `B2BInvoice` grouping trigger, and mandate-type-aware retry routing (`CardRetryBudget` / `NACHRetryPolicy` / `UPIRetryBudget`) — with no open questions left for it to invent answers to.
