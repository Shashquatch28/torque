# Torque — Module 1, Rev. 5 (Final Lock)
### Resolution of the v4 Critique — Nine Items, Each Closed and Self-Audited
> Per your instruction: every fix below is followed by an explicit audit against the specific failure mode the critique named. Where a fix is architectural, it's locked. Where a fix depends on data that can only be confirmed against Razorpay's live acquirer output, that's stated plainly as a tracked validation step — not folded silently into the lock, and not used as a reason to leave the architecture undecided either. That distinction is what makes this lock different from the last one.

---

## I + II. MAC classification — reconciled, not re-asserted

**What the research found:** three genuinely different things were being treated as one.

1. **Mastercard's own Merchant Advice Code value set** — a small, Mastercard-defined list: `01, 02, 03, 04, 05, 21, 22, 24–30, 40, 41, 42...`. These are the actual codes that arrive in the authorization response.
2. **A "Category 1/2/3/4 reversibility" taxonomy** used by some processor abstraction layers (Yuno and similar), built on raw ISO decline/response codes (`04, 07, 12, 15, 41, 43, 46, 51, 57...`). This is a *different numbering space* that happens to share digits with (1) — its "41" is not Mastercard's MAC 41. This is exactly the collision you flagged in Issue II, and it's real: Mastercard's own documentation defines MAC 41 as "Consumer Single-Use Virtual Card Number" (introduced Oct 2023, explicitly **no fee attached**), which has nothing to do with the reversibility-taxonomy's "41."
3. **Two independent Mastercard TPE enforcement mechanisms**, not one: (a) **Excessive Authorization Attempts** — volume-based, counts any repeated decline regardless of MAC content, thresholds 10/24h + 35/30d; (b) a **MAC 03/21-specific fee** — triggers on the very first retry after either code, no volume threshold, and applies *only* to 03/21, not to the broader reversible-code set.

**Locked architecture** — a three-tier model justified by mechanism (b) and (a), not by the incidental reversibility taxonomy that originally caused the conflation:

| Tier | Codes | `hard_stop` | `hard_stop_reason` | Policy behavior |
|---|---|---|---|---|
| 1 — Network hard-stop, fee from first retry | MAC `03`, `21` | `true` | `NETWORK_HARD_STOP` | Stop all contact tied to this payment method, permanently |
| 2 — Capped retry, volume-metered only | MAC `5C`, `9G`, other issuer-temporary codes | `false` | — | Counts toward `attempts_used_24h`/`_30d`; retry permitted within cap |
| 3 — Instrument dead, no fee, retry futile | MAC `40`, `41` | `true` | `INSTRUMENT_NOT_RECURRING_CAPABLE` | Distinct branch: stop retrying *this instrument*, immediately route to "request new payment method," not silence |
| Timed | MAC `24`–`30` | `false` | — | Honor the specified retry-after window (unchanged from Rev. 4) |

Tier 3 gets its own `hard_stop_reason` specifically because your Issue II point was correct: collapsing it into the same boolean as Tier 1 loses a real behavioral distinction (Module 4 should ask for a new card, not go silent).

**What stays explicitly open, and how it's tracked (not hedged):** the mapping from Razorpay's actual acquirer-level decline payload to one of these four tiers. This is not an architectural gap — it's a data-population task. Add one new construct: a static **`MacCodeRegistry`** config table — `(network, mac_code) → tier` — seeded with the mapping above. Module 5 validates this table's rows against Razorpay's live gateway responses before production traffic, and any acquirer-specific correction is a row update in that table, not a redesign. This is the mechanism that resolves the self-contradiction from Rev. 4: the *tiering model* is locked; the *specific code-to-tier assignment for this acquirer* is a checklist item that plugs into the model without requiring the model to change.

**Self-audit:** Does this stop conflating the two classification systems? Yes — the tier boundaries now come from the TPE fee mechanism (verified across independent 2026 sources), not the reversibility taxonomy that put 03 and 5C in the same bucket for an unrelated reason. Does it fix the 41-code-space collision? Yes — Tier 3 is sourced from Mastercard's own MAC documentation, not the Yuno-style taxonomy, and the two are explicitly named as different numbering spaces so Module 5 doesn't reintroduce the collision. Does "locked" still mean something? Yes — a reader now knows exactly what to do with any of the four tiers; only the empirical *which-code-is-which-tier-for-this-acquirer* step remains, and it has a named home (`MacCodeRegistry`) instead of a hedge in prose.

---

## III. `CardRetryBudget` off-by-one — fixed at the source

**Fix:** the counter is no longer seeded at zero and incremented only by Module 5's retry actions. It's seeded at **case creation**: when Module 2 ingests the *originating* declined-payment event that creates the `RevenueLeakCase` in the first place, that same event increments `CardRetryBudget.attempts_used_24h` and `attempts_used_30d` to 1 (upserting the row if it doesn't exist). Every subsequent Module 5 `RETRY_PAYMENT` action increments the same counters. Both write paths — Module 2's ingestion-time upsert and Module 5's pre-retry decrement-check — touch the same row, and the Module 2 write happens in the same transaction as the `RevenueLeakCase` + `Event` insert, for the same reason Issue II required atomic `Action`+`CaseEvent` writes: a counter update that can silently fail independently of the row it's protecting reintroduces exactly the consistency gap this entity exists to close.

**Self-audit:** Does Torque's count now match what Mastercard is counting? Yes — both start from the same originating decline. Does this reintroduce a dual-write gap of its own? No — explicitly scoped into the same transaction boundary as the case-creation write, not a separate step that can drift.

---

## IV. NACH retry posture — stated, not assumed

**What the research found:** NACH has **no NPCI-standardized fixed attempt cap** analogous to UPI AutoPay's 4-attempt rule. NACH dishonour consequences are bank-discretionary and cumulative: banks track dishonour *frequency per financial year* (commonly a 3–5 occurrence threshold before consequences like mandate-registration refusal), applied at the **account level**, and at some banks combined across NACH *and* cheque dishonours on the same account — not a fixed per-mandate, per-cycle number set by NPCI.

**Fix, stated explicitly rather than by omission:**
- `NACHRetryPolicy` gains `dishonour_count_this_fy` (Int, running counter per mandate — a conservative proxy, since Torque doesn't have visibility into a counterparty's cheque-dishonour history at other accounts).
- `Playbook.stopping_rules.max_attempts` for NACH playbooks carries a **merchant-configurable ceiling with a recommended conservative default of 3 representments per billing cycle** — explicitly documented as a **self-imposed ceiling chosen to stay under typical bank frequent-dishonour thresholds**, not a network-enforced number the way `UPIRetryBudget.hard_cap` is.
- True cross-instrument (cheque + NACH combined) account-level aggregation is 🔮 roadmap — it requires bank-side visibility Torque doesn't have.

**Self-audit:** Does this state the asymmetry between the three retry rails, or leave it for a reader to notice by omission? It's now explicit: card = network-metered dual-window, UPI AutoPay = network-hard-capped at 3 retries, NACH = merchant-self-capped with no network number to cite. Three genuinely different compliance postures, named as such.

---

## V. `UPIRetryBudget` execution window — added as a second, independent gate

**Confirmed:** NPCI's peak-hour definition for UPI (per its own API-usage guidelines, effective Aug 1, 2025) is **10:00–13:00 and 17:00–21:30 IST**. AutoPay execution is restricted to the complement of that window.

**Fix:** `UPIRetryBudget` gains `permitted_execution_window`, evaluated by Module 5 as a check **independent of and in addition to** `Playbook.stopping_rules.allowed_hours`. The two serve different purposes and must both pass: `allowed_hours` governs when it's acceptable to *contact* the customer (a compliance/UX choice, e.g., 08:00–19:00); `permitted_execution_window` governs when NPCI's infrastructure will accept the *debit attempt itself*, regardless of contact considerations. A retry scheduled at 11:00 could sit comfortably inside `allowed_hours` and still fall inside NPCI's peak window — the two checks are not substitutes for each other.

**Self-audit:** Is the network-imposed execution constraint now distinct from the customer-contact constraint, as the critique required? Yes — separate field, separate check, explicit statement that passing one doesn't imply passing the other.

---

## VI. `SystemicEvent` — network-wide detection tier added

**Verified:** the specific claim in the v4 critique — UPI suffered three outages in a single month in 2025 (March 26, April 2, April 12) — checks out against multiple independent reports, and all three were network-wide (multi-bank, NPCI-infrastructure-level), not single-issuer events. This confirms the gap: a per-issuer ratio-to-own-baseline check can miss a proportional, simultaneous spike across every issuer.

**Fix:** `SystemicEvent` gains a `scope` field: `ISSUER_SPECIFIC` | `NETWORK_WIDE`. The network-wide tier runs the same floor-plus-sustain-window logic from Rev. 4's Issue XI fix, but compares **aggregate failure rate across all issuers** against the **merchant's own historical aggregate baseline**, rather than any single issuer's baseline. A `NETWORK_WIDE` `SystemicEvent` suppresses diagnosis across every issuer for the merchant, not just the one that crossed its individual threshold.

**Self-audit:** Does this catch the failure mode the critique named — a proportional cross-issuer spike that no single issuer's own ratio flags? Yes, by construction — the aggregate check doesn't depend on any one issuer crossing 5× its own baseline. Is the underlying factual claim justifying this fix actually true? Verified yes, not just repeated from the critique.

---

## VII. `ActionCase.credit_weight` — invariant stated as a constraint, not a comment

**Fix:** "The sum of `credit_weight` across all `ActionCase` rows sharing an `action_id` must equal exactly 1" is now specified as a **database check constraint** (or, where the DB can't express a cross-row sum constraint directly, an application-layer validation enforced at write time in the same transaction as the `ActionCase` inserts) — not a documentation note that a future implementer could miss.

**Self-audit:** Does this close the silent over/under-crediting risk? Yes. Is it enforced rather than merely stated? Yes — explicitly named as a constraint, not prose, precisely because "stated in a design doc but not enforced in code" is the same category of bug as the original `step_history` contradiction in v3: two things that were supposed to be the same weren't actually forced to be.

---

## VIII. SMS decision — demo path and production gate separated

**Confirmed:** TRAI's DLT framework (TCCCPR) requires **every** business sending commercial SMS to Indian numbers to register an entity, sender ID, and per-template content — no volume exception, no intent exception. Fast2SMS's free-credit test route is legitimately outside this for small-scale testing, but does not generalize to production sending.

**Fix — Decision I, corrected wording:** *"Demo: Fast2SMS ₹50 free-credit signup, Quick SMS test route, no DLT template required — 🔧 build for demo, capped to pre-verified test numbers, same pattern as the WhatsApp and email demo paths. Production: any SMS sending at scale requires full TRAI DLT registration — Principal Entity registration, Sender ID approval, and per-template pre-approval, a multi-day process structurally identical in kind to WhatsApp's Meta template-approval gate and Razorpay's own onboarding gates elsewhere in this document. This is 🔮 roadmap, named explicitly so it isn't mistaken for solved-at-scale."*

**Self-audit:** Does this now carry the same demo-vs-production honesty that CAU and WhatsApp billing already get elsewhere in the blueprint? Yes — SMS was the one channel getting a pass on that distinction, and it no longer does.

---

## IX. `PreDebitNotification` — amount added

**Fix:** add `notified_amount` to the `PreDebitNotification` table (Rev. 4, Issue VI). The RBI e-mandate framework's substantive requirement is that the customer be told what will be debited, not merely that a debit is coming — and the amount can legitimately differ between the original mandate and a retry (proration, partial-recovery scenarios in B2B-adjacent cases). One column; closes the gap between "a notification was sent" and "the legally sufficient notification was sent."

**Self-audit:** Does the table now capture what RBI's framework actually requires be communicated, not just that something was communicated? Yes.

---

## Closing status

All nine items are closed. Three of them (I/II, III, VI) required correcting or sharpening a factual claim the project had been carrying since v1 or introduced in v4 — the 5C/9G-vs-03/21 conflation, the CardRetryBudget seeding gap, and the per-issuer-only systemic detection — and all three are now grounded in independently verified sources rather than restated assertions. Three (IV, VIII) required stating an asymmetry or a limitation explicitly instead of leaving it to be inferred. Three (V, VII, IX) were single-field additions closing precise, narrow gaps.

The one piece of intentional, named non-closure is the `MacCodeRegistry` empirical mapping — and it's non-closure by design, not by oversight: architecture doesn't get to decide which MAC code a specific acquirer sends for a specific decline reason, only what to do once it's known. That's now a Module 5 implementation checklist item with a table to populate, not an open question sitting in Module 1.

**Module 1: 🔒 LOCKED.**
