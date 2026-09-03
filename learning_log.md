# Torque — Product Learning Log

> A personal study sheet for explaining Torque to an investor, customer, judge,
> partner, or technical interviewer **without opening the code**. It is cumulative
> — Modules 1–7 are all captured here. It is deliberately *not* an implementation
> changelog; code-level facts appear only when translated into something you can
> say in a pitch.

---

## 1. One-Minute Product Explanation

**Torque is an autonomous revenue-recovery agent for businesses that take
recurring or online payments.** When money that *should* have arrived doesn't —
a card declines, a subscription auto-charge fails, a checkout is abandoned, a B2B
invoice goes overdue — Torque detects it, works out *why*, runs a bounded,
compliant recovery sequence (a smart retry, a nudge over WhatsApp/email, a fresh
payment link, a dunning thread), and then **proves how much revenue it actually
brought back** versus what would have come back anyway.

It replaces what a merchant does today with three or four disconnected tools and
a spreadsheet, and it does it under hard payment-network and consent rules baked
into the system rather than bolted on.

Who it's for: subscription businesses, D2C brands, SaaS companies, marketplaces,
and B2B sellers on payment infrastructure like Razorpay — anyone with a
measurable "failed payment" and "overdue receivable" problem.

---

## 2. The Problem

Every business that bills customers loses a slice of revenue to **payment
friction that is recoverable but nobody systematically recovers it**:

- **Payment degradation** — a customer's card is declined at the gateway
  (insufficient funds, an issuer hiccup, a temporary block). A large share of
  these succeed on a second attempt *if it's timed right and allowed by the card
  network's rules*.
- **Subscription / mandate failure** — an auto-debit (UPI AutoPay, e-NACH,
  card-on-file) fails on renewal. Left alone, the customer churns silently.
- **Checkout abandonment** — the customer got to the payment step and dropped.
  Sometimes it's price; sometimes it's a fixable friction (e.g. they were typing
  a UPI ID and gave up — offering the one-tap intent flow instead often works).
- **B2B receivables** — an invoice is overdue. Chasing it is manual, inconsistent,
  and easy to drop.

**Why existing processes struggle:**

- **Fragmentation.** A merchant stitches together a retry tool, a dunning tool, a
  cart-recovery tool, and a collections process — four logins, four dashboards,
  four different definitions of "recovered revenue," no shared view of the
  customer.
- **Blunt automation.** Naive retry logic hammers a dead card, which in card
  networks like Mastercard triggers **per-attempt fees** and can get a merchant
  penalised. Naive dunning keeps messaging a customer who already paid, or
  messages during a live support conversation.
- **No attribution.** When the money comes back, nobody knows whether the tool
  caused it or the customer would have paid regardless. So "recovered revenue"
  numbers are vanity numbers.
- **Compliance is an afterthought.** Card-network retry caps, RBI e-mandate
  pre-debit notice rules, WhatsApp's consent + approved-template requirements,
  NPCI's UPI peak-hour windows — each is a place to get fined or shut off, and
  each is usually handled ad hoc.

**Why it's economically important:** the leaked revenue is *already sold* — the
customer wanted to pay. Recovering even a portion of it is close to pure margin,
and doing it without extra customer annoyance or compliance risk is the hard part
that makes it defensible.

---

## 3. How Torque Works (end-to-end)

1. **Detect.** Torque ingests events from the payment stack (declined payments,
   failed subscription charges, overdue invoices) and a lightweight signal for
   checkout abandonment. Every event is cryptographically verified before it is
   trusted, and de-duplicated so the same event is never processed twice.

2. **Wait out the noise.** For a live payment failure, Torque holds briefly (~90
   seconds) to see if the customer just retries and succeeds on their own — if so,
   no revenue actually leaked and Torque does nothing. Subscription failures get a
   shorter hold.

3. **Open a case.** If the money is genuinely missing, Torque creates one
   **Revenue Leak Case** — the single shared record for this loss. If the same
   loss is showing up under two signals (an abandoned cart *and* then a declined
   payment for the same order), Torque **merges** them into one case instead of
   double-counting.

4. **Diagnose the root cause.** Torque classifies *why* the payment failed —
   insufficient funds vs. a hard "do not retry" decline vs. an expired card vs. a
   dead instrument vs. a gateway timeout — and attaches a **confidence score**. If
   it can't be confident, the case is routed to a human instead of guessed at.

5. **Suppress during outages.** If Torque sees a spike of failures that looks like
   a bank or network outage rather than individual problems, it puts affected
   cases on hold and doesn't waste retries or annoy customers during the outage.

6. **Select a playbook.** Based on the root cause and the leg, Torque picks a
   **bounded recovery playbook** — a short, pre-authored sequence of steps (e.g.
   "retry now → wait for payday → nudge over WhatsApp → escalate to a human"). The
   playbook is version-pinned so a mid-flight case finishes on the plan it
   started with.

7. **Execute under guardrails.** Before *every* automated action, Torque runs it
   past the **Compliance Guardrail Engine**: card-network retry budgets,
   "do-not-retry" network directives, the RBI 24-hour pre-debit notice, UPI
   peak-hour windows, WhatsApp consent + approved templates, a live-conversation
   check, quiet hours, and a cross-leg "don't contact this person about two
   different things within 4 hours" rule. An unsafe action is **blocked**; an
   action that's just badly timed is **deferred** (rescheduled), not abandoned.

8. **Coordinate outreach.** If two cases for the same customer are both due to be
   contacted, the **Outreach Coordinator merges them into one message** that
   references both amounts, so the customer gets one coherent ask, not two.

9. **Escalate when automation is spent.** If a recovery keeps hitting dead ends,
   or a captured promise-to-pay is broken, or the diagnosis was low-confidence,
   the case goes into a **per-merchant human queue**, ordered by economic value.

10. **Reconcile the money.** When a payment success signal arrives —
    `payment.captured`, `subscription.charged`, or a payment-link `paid` — Torque
    **matches it back to the leaking case**, decides **who gets credit** (Torque,
    the customer self-recovering, or ambiguous), splits credit fairly across
    merged cases, and **closes the case correctly** (fully recovered, or, for B2B,
    partially recovered with the remaining balance still being chased).

11. **Measure lift (design in place).** Cases are assigned to treatment vs. a
    held-out control cohort *per customer relationship* so Torque can eventually
    report **incremental** recovery — the revenue it actually caused — with honest
    confidence intervals, not just gross totals. (The reporting surface itself is
    a later module.)

---

## 4. Core Product Concepts

- **Revenue Leak Case** — the atomic unit. One record per underlying loss,
  shared by every part of the system. It carries the amount at risk, the leg, the
  counterparty, the diagnosed root cause, the network directive, the status, and
  (once resolved) how it was recovered.

- **Leg** — which of the four funnels the loss came from: *payment degradation*,
  *checkout abandonment*, *subscription/mandate failure*, *B2B receivable*. The
  same engine handles all four; the leg mainly changes the playbook and timing.

- **Counterparty** — the customer or business on the other side. Identity/consent
  live in exactly one place; per-merchant relationship history (promise-keeping
  rate, risk, cohort) lives on a join record so the same person can be a customer
  of several merchants without data bleeding across them.

- **Root Cause / Diagnosis** — the classified reason a payment failed, with a
  confidence score. Low confidence deliberately routes to a human rather than a
  guess.

- **Network Directive** — a machine-readable instruction from the card network
  (e.g. Mastercard MAC codes) that says "safe to retry within limits," "retry
  after N hours," "this instrument is dead — ask for a new one," or "do not retry,
  a fee applies." Torque always obeys the most restrictive directive it has ever
  seen on a case.

- **Playbook** — a pre-authored, bounded recovery sequence for a given root
  cause: a small graph of steps with timing, stopping rules (max attempts, max
  duration, allowed contact hours, an escalation ceiling), and a version. Runs
  pin their version.

- **Playbook Run** — one execution of a playbook against a case. It has a single
  "current step" pointer and is driven by a durable timer.

- **Action** — one thing Torque did (or was blocked from doing) on a case: a
  payment retry, a WhatsApp/email/SMS message, a payment link, a promise capture,
  an escalation. Every action records its outcome and its cost, and every action
  is written **together, in one transaction, with an entry in the case's audit
  ledger**.

- **Guardrail** — a compliance/safety/timing/consent/budget check run
  immediately before an action. Outcomes: allow, **block** (unsafe — write it as
  blocked and move on), **defer** (badly timed — reschedule), or **self-heal**
  (e.g. auto-insert the missing pre-debit notice, then retry 24h later).

- **Compliance Guardrail Engine** — the single component every automated action
  is checked against, in a fixed order, first-failure-wins. It is the "one place"
  that makes "compliance by construction" real instead of a slogan.

- **Outreach Coordinator** — owns cross-case, cross-leg contact discipline: the
  4-hour quiet period between different-leg messages to one customer, the merge of
  two due outreaches into one message, deferral instead of dropping, and
  suspending automated templates while a live WhatsApp conversation is open.

- **Human Escalation / Human Queue** — a per-merchant, economically-ordered
  queue of cases that need a person: low-confidence diagnoses, recoveries that
  exhausted their automation ceiling, and broken promises-to-pay. Torque routes
  *into* it; a human agent console is a later module.

- **Recovery** — the money coming back. A case is **Recovered** (full),
  **Partially Recovered** (B2B, balance still owed), **Cancelled** (the customer
  self-paid before Torque even acted), **Exhausted** (automation ran its course
  with no recovery), or **Escalated to Human**.

- **Reconciliation** — matching an incoming payment-success signal to the case
  that was leaking, so a real recovery closes the real case and doesn't sit as a
  mystery credit.

- **Attribution** — deciding *who caused* a recovery: **Agent-Assisted** (Torque
  acted within the attribution window), **Self-Recovered** (the customer paid with
  no Torque action), or **Ambiguous** (a payment matched more than one case and
  Torque can't be certain which). This is what turns "recovered revenue" into an
  honest number.

- **Multi-case recovery** — when Torque merged two cases into one outreach and a
  single payment settles both, it splits recovery credit proportionally to each
  case's amount at risk.

- **Systemic Event** — a detected bank/network outage that suppresses
  individual-case outreach for its duration.

- **Incrementality / Control Cohort** — a per-customer-relationship assignment to
  treatment or a held-out control group, so lift can be measured as *incremental*
  recovery. The assignment is built in; the measurement report is a later module.

- **CaseEvent ledger** — the single, append-only history of everything that
  happened to a case. It cannot be edited or deleted. It is both the audit trail
  and the "why did the agent do this" explanation surface.

---

## 5. Feature-by-Feature Explanations

### 5.1 Verified, de-duplicated signal ingestion

- **What:** every inbound event (declined payment, failed charge, overdue
  invoice, abandoned checkout) is cryptographically verified before it is trusted,
  and de-duplicated on the payment provider's own event id.
- **Why:** you cannot build a money system on unverified or double-counted
  events. A forged or replayed "payment failed" must never open a case; a real
  event delivered twice must never open two.
- **How:** signature check on the raw request *before* the body is even parsed;
  a unique key from the provider's event-id header; unknown or unverified requests
  are silently dropped with no trace.
- **Example:** the provider retries a webhook 3 times after a network blip —
  Torque records one event, opens one case.
- **Business value:** trustworthy inputs; no phantom cases inflating (or
  deflating) numbers; no fraud vector.
- **Differentiator:** verification and idempotency are a **cross-cutting
  requirement**, not a feature that some code paths remember to do.
- **Status:** implemented (all four legs).

### 5.2 The same-session self-recovery hold

- **What:** after a live payment failure, Torque waits ~90 seconds before doing
  anything. If the customer simply retries and succeeds in that window, Torque
  creates **no case at all**.
- **Why:** that failure/success pair is invisible, same-session friction — no
  revenue actually leaked, so touching it would be noise (and would pollute the
  recovery numbers).
- **How:** a short delayed job that checks for an interim success signal for the
  same payment/order.
- **Business value:** the numbers only ever reflect *real* leakage; customers
  aren't messaged about a problem they already fixed.
- **Status:** implemented (payment degradation 90s; subscription failure 30s).

### 5.3 Cross-leg case merge (one ledger)

- **What:** if the same underlying loss surfaces as two signals (abandoned cart,
  then a declined payment for that order), Torque folds them into **one case** and
  keeps both signals' diagnostic context.
- **Why:** two tools would count this as two recoveries. One shared case object
  is the whole point of "one ledger."
- **How:** a time-bounded correlation on merchant + customer + cart/order id; the
  narrower signal's case is superseded into the more diagnostically specific one.
- **Business value:** honest counts; better diagnosis (more signal on one case).
- **Differentiator:** "one case object across all four legs" — the fragmentation
  fix, demonstrated rather than asserted.
- **Status:** implemented, both directions.

### 5.4 Root-cause diagnosis with confidence

- **What:** Torque classifies *why* a payment failed — insufficient funds, a hard
  fraud/closed-account decline, an expired card, a structurally non-recurring
  instrument, a gateway timeout, a still-clearing bank batch, a cancelled mandate
  — and attaches a 0–1 confidence.
- **Why:** the recovery action depends entirely on the reason. Retrying a
  "do-not-retry" decline costs money; retrying insufficient funds *after payday*
  often works.
- **How:** rule-based classification over the decline code, the card-network
  directive (which takes precedence), and mandate-type facts; a policy threshold
  (launch value 0.65) below which the case is sent to a human instead of a
  playbook.
- **Example:** a debit card fails with an insufficient-funds code → root cause
  "NSF soft decline," and the diagnosis emits a hint to time the retry toward the
  next salary date.
- **Business value:** higher recovery rate, lower wasted spend, fewer
  compliance hits, fewer annoyed customers.
- **Differentiator:** it's the "why," not just the "what" — and the honest
  low-confidence-to-human routing is a feature, not a gap.
- **Status:** implemented (rule-based; an ML upgrade path is designed, not built).

### 5.5 Outage suppression (Systemic Events)

- **What:** if Torque sees a proportional spike of failures that looks like a
  bank/network outage, it holds affected cases and stops outreach until the
  outage clears.
- **Why:** during an outage, retries fail anyway and messages just annoy people —
  and it can look like *your* problem.
- **How:** a compound threshold (rate ≥ 5× a rolling baseline, plus absolute
  floors) computed on a short cadence; a sustained quiet window before the hold is
  released and cases are re-queued.
- **Business value:** protects sender reputation and customer trust; avoids
  burning retry budget on a doomed window.
- **Status:** network-wide detection implemented; per-issuer detection is
  designed but blocked on issuer data extraction.

### 5.6 Bounded recovery playbooks

- **What:** a small, pre-authored sequence of recovery steps per root cause, with
  timing, stopping rules, allowed contact hours, and an escalation ceiling. A
  running recovery pins its playbook version.
- **Why:** unbounded automation is how you get fined and how you churn customers.
  "Bounded" is the safety property.
- **How:** a validated step graph (every step has exactly one success edge and at
  least one fallback, no cycles); merchant-tunable stopping rules within hard
  caps; version pinning so a live run isn't disturbed by an edit.
- **Business value:** predictable, explainable customer experience; a hard cap on
  how much Torque can do before a human takes over.
- **Status:** implemented (eleven demo playbooks; the catalog is validated at
  save time).

### 5.7 The Compliance Guardrail Engine

- **What:** every automated action is evaluated against a fixed sequence of
  compliance, safety, budget, timing, consent, and outreach rules before it fires.
  Unsafe → **blocked**; badly timed → **deferred** (rescheduled, never dropped);
  a fixable compliance gap → **self-healed** (e.g. auto-send the missing pre-debit
  notice, then retry after the mandatory 24 hours).
- **Why:** this is the difference between "we try to be compliant" and
  "non-compliant actions are structurally impossible."
- **The rules, in order:** card-network "do-not-retry" hard stop → per-instrument
  retry budgets (Mastercard's dual-window volume caps, NPCI's UPI 1+3 cap,
  bank-discretionary NACH ceilings) → the RBI e-mandate 24-hour pre-debit notice →
  outage hold → for customer contact: the 4-hour cross-leg quiet period → outreach
  merge → WhatsApp consent + an approved template of the right category →
  suspend-if-a-live-conversation-is-open → quiet hours.
- **How:** one callable interface (`GuardrailEngine.check`) that the execution
  layer consults for every action, first-failure-wins. Module 5 (execution) owns
  *doing* the action and the atomic write; Module 6 (this engine) owns *deciding
  whether it's allowed at all* — a clean ownership line so the logic can't drift.
- **Example:** a UPI AutoPay retry comes due at 11:30 — inside NPCI's declared
  peak window — so Torque **defers** it to just after 13:00 rather than failing
  the step.
- **Business value:** compliance-by-construction; the exception list (every
  blocked action, grouped by reason) is *evidence of restraint* a merchant can
  show a regulator or an auditor.
- **Differentiator:** the strongest one. A system demonstrably *not* doing things
  it isn't allowed to do is harder and more credible than a system doing a lot.
- **Status:** implemented.

### 5.8 The Outreach Coordinator

- **What:** cross-case contact discipline. A 4-hour minimum between messages to
  one customer about *different* legs; two due outreaches for one customer merged
  into a single message that names both amounts; deferral (not cancellation) when
  a message would land in a quiet window; and suspension of automated templates
  while a live WhatsApp service conversation is open (route to a human instead).
- **Why:** a customer who gets three separate Torque messages in an afternoon
  unsubscribes. Coordinated, minimal contact is both better UX and better
  deliverability.
- **How:** priority is `(probability × amount at risk) ÷ cost` per case — the
  same economic formula used everywhere in the system; the higher-priority case
  owns the merged message; recovery credit is later split proportionally.
- **Example:** the same customer has an overdue invoice and a failed subscription
  renewal — Torque sends one message: "You have ₹4,000 in outstanding items with
  us," not two.
- **Business value:** fewer opt-outs, better sender reputation, one coherent
  customer relationship.
- **Differentiator:** resource-aware prioritisation — a ₹50,000 subscription
  failure outranks a ₹500 invoice by economics, not by a fixed leg ordering.
- **Status:** implemented. The `probability` term currently uses a placeholder
  (amount at risk); the full Module 8 score plugs into the same seam.

### 5.9 Escalation ceiling & the human queue

- **What:** when a recovery accumulates enough unsuccessful attempts (blocked,
  failed, or no-response), Torque stops automating and routes the case to a
  per-merchant human queue — *before* firing another doomed action. The queue also
  receives low-confidence diagnoses and cases where a customer's promise-to-pay
  was broken. It's ordered by the same economic score.
- **Why:** "when do we give up on automation" is a policy decision, not an
  accident of a loop running out. And a broken promise should reach a human, never
  a harsher bot message.
- **How:** a single check in the execution lifecycle transitions the case to
  "escalated to human," records it, and puts it in the queue; a resolved case is
  automatically removed from the queue.
- **Business value:** humans spend time on the cases worth their time; automation
  never becomes harassment.
- **Status:** implemented (routing in; the agent console that a human *uses* is a
  later module).

### 5.10 Payment reconciliation & recovery attribution  *(Module 7 — newest)*

- **What:** when a payment-success signal arrives, Torque matches it to the case
  that was leaking, decides who caused the recovery, splits credit across merged
  cases, and closes the case correctly.
- **Why:** without this, "recovered revenue" is a guess. This is the feature that
  makes Torque's headline number *defensible*.
- **How — the matching ladder:**
  1. **Direct** — the payment came through a Torque-generated payment link →
     credit that link's case fully, mark it **Agent-Assisted**.
  2. **Indirect** — the customer paid directly (their own bank/UPI app). Match on
     merchant + customer + amount. Exactly one open case → attribute to it;
     **Agent-Assisted** if Torque took an action on that case in the last 24
     hours, otherwise **Self-Recovered**.
  3. **Multiple cases match** — if they were merged into one outreach, re-split
     the credit proportionally to each amount and recover them all; if they
     genuinely can't be told apart, attribute to the most-recently-worked case as
     **Ambiguous** and leave the others open.
  4. **No open case matches** — but there's a case still in detection/diagnosis
     for that customer and amount → the customer self-paid before Torque could
     act; close it **Cancelled / Self-Recovered**.
- **Closure rules:** full amount → **Recovered**, close the case. B2B partial
  payment → **Partially Recovered**, apply it to the oldest invoice first, keep
  chasing the rest, and the case's amount-at-risk follows the outstanding balance.
- **Inputs:** verified success events (`payment.captured`, `subscription.charged`,
  `payment_link.paid` / `partially_paid` / `expired` / `cancelled`); the case's
  action history; the customer identity; the payment-link record.
- **Outputs:** a closed (or partially closed) case with a `recovery_type` and
  `recovered_amount`; an updated payment-link record; a `PAYMENT_RECONCILED` entry
  in the audit ledger; the case removed from the human queue if it was there.
- **Guarantees:** the whole reconciliation of one event is one transaction; a
  redelivered event is a no-op; two workers reconciling different payments for the
  same case can't both close it (the case row is locked); a merchant-B case is
  never reconciled by a merchant-A payment.
- **Example:** a subscription renewal failed 3 days ago, Torque sent a WhatsApp
  nudge yesterday, today `subscription.charged` arrives for the same customer and
  amount → the case closes **Recovered / Agent-Assisted**, and that ₹ counts
  toward Torque's lift.
- **Business value:** turns gross "recovered" into **attributed** recovery — the
  only number a CFO or investor should believe.
- **Differentiator:** the payment-link path is the cleanest attribution signal in
  the industry (Torque *generated* the link, so a payment on it is unambiguously
  agent-assisted); the honest **Ambiguous** category is a credibility signal, not
  a bug.
- **Status:** implemented. The direct payment-link path is fully wired for links
  Torque already holds a record for; it becomes end-to-end once the link-creation
  action is switched from stub to live.

### 5.11 Append-only audit & explainability

- **What:** every status change, action, block, diagnosis, and reconciliation is
  a row in one append-only ledger per case. It can't be edited or deleted, and no
  event type can be written without a matching, validated payload schema.
- **Why:** money systems need a tamper-evident history; and "why did the agent do
  this?" should be a query, not a debugging session.
- **How:** a database trigger *and* an application guard both refuse mutation;
  every `Action` and its ledger entry are written in the same transaction.
- **Business value:** audit-ready by default; the same data powers the merchant's
  "Agent Reasoning" panel.
- **Status:** implemented.

### 5.12 Multi-tenancy & data isolation

- **What:** every merchant's cases, actions, budgets, templates, and queue
  entries are strictly scoped to that merchant. Customer identity is stored once
  globally; all *relationship* data is per-merchant.
- **Why:** it's a multi-merchant platform touching PII and money.
- **How:** a single always-injecting data-access layer; cross-tenant reads return
  nothing, cross-tenant writes raise.
- **Business value:** a clean SaaS security story; DPDP-aligned PII handling
  (single source, erasure = null-in-place, history stays intact).
- **Status:** implemented.

---

## 6. Module-by-Module Product Story

*(What each module contributes to the product — not its code layout.)*

- **Module 1 — Core Data Model.** The shared spine: one Revenue Leak Case object,
  one append-only event ledger, the compliance entities (retry budgets, pre-debit
  notices, network-directive tiers), PII/consent handling, and the state machine
  for a case's life. "One ledger, four legs" starts here.

- **Module 2 — Signal Ingestion.** Turns raw provider webhooks into trustworthy
  cases: verify-before-parse, idempotency, the self-recovery hold, cross-leg
  merge, and outage detection. All four legs land here.

- **Module 3 — Diagnosis Engine.** Works out *why* a payment failed and how
  confident it is; routes low-confidence cases to humans by construction. This is
  the "root-cause, not symptom" differentiator.

- **Module 4 — Policy & Playbook Engine.** Chooses the bounded recovery playbook
  for a diagnosed case and instantiates a version-pinned run. Owns the rules for
  authoring and reading a playbook graph.

- **Module 5 — Execution & Orchestration.** Actually runs a playbook over time on
  a durable timer: resolve the current step, run the guardrails, perform the
  action, record it atomically, advance, reschedule. Retry-budget consumption,
  payday-aware timing, allowed-hours deferral. (Real message/charge *delivery* is
  a stub in the demo — Torque fires nothing externally yet, which is safe by
  construction.)

- **Module 6 — Compliance & Cross-Leg Guardrail Engine.** The single decision
  point for "is this action allowed?", plus the Outreach Coordinator (quiet
  period, merge, defer, live-conversation suspension), the escalation ceiling, and
  the human queue. This is where "compliance by construction" and "coordinated,
  minimal contact" become real.

- **Module 7 — Payment Reconciliation & Attribution.** Closes the loop: matches
  incoming payments to leaking cases, decides Agent-Assisted vs. Self-Recovered
  vs. Ambiguous, splits credit across merged cases, and closes cases correctly
  (including B2B partial payments). This is what makes Torque's recovered-revenue
  number honest.

- **Modules 8–13 (not built).** Recovery scoring model (the real
  `(probability × amount) ÷ cost`), reporting & incrementality measurement, UI
  (merchant dashboard, agent console, demo surface), infra, roadmap, demo script.

**"What did you actually build?"** — the entire closed loop from a verified
failure signal through diagnosis, bounded compliant recovery, coordinated
outreach, human escalation, and **attributed** reconciliation, on one shared case
object with an append-only audit trail, under real card-network / RBI / NPCI /
WhatsApp rules. What's *not* built: real outbound message/charge delivery, the ML
scoring model, and the reporting/UI layer.

---

## 7. End-to-End Example

**Setup.** "NorthPeak Coffee" sells a ₹499/month subscription on Razorpay via UPI
AutoPay. A subscriber, Priya, has a renewal due.

1. **Failure.** Priya's UPI AutoPay renewal fails — insufficient balance.
   Razorpay sends `subscription.charged.failed`. Torque verifies it and holds 30
   seconds; no interim success arrives.

2. **Case.** Torque opens Revenue Leak Case #C-1042: leg = subscription failure,
   amount at risk = ₹499, counterparty = Priya (for NorthPeak specifically).

3. **Diagnosis.** Decline code + mandate type → root cause "NSF soft decline,"
   confidence 0.75 (above the 0.65 threshold), with a hint: time the retry toward
   payday.

4. **Playbook.** Torque selects the UPI AutoPay retry playbook: send the RBI
   pre-debit notice → wait → retry → nudge over WhatsApp → escalate. Stopping
   rules: max 3 attempts (NPCI cap), escalation ceiling 2.

5. **Execution + guardrails.**
   - Step 1 is the pre-debit notice — guardrails pass, it's "sent" (stub).
   - Step 2, the retry, comes due at 11:00 IST — inside NPCI's peak window — so
     the guardrail engine **defers** it to 13:05.
   - At 13:05 the retry runs; it fails again (still no funds). Attempt count: 2 of
     3.

6. **Outreach coordination.** A WhatsApp nudge is due. Priya also has a separate
   overdue invoice case with NorthPeak (she runs a small café that buys beans
   wholesale). Both are due to be contacted. The Outreach Coordinator **merges**
   them: one WhatsApp message referencing ₹499 (subscription) + ₹3,000 (invoice) =
   ₹3,499 outstanding. Consent + approved template check passes.

7. **Priya pays.** She opens her UPI app and pays ₹3,499 directly.

8. **Reconciliation (Module 7).** `payment.captured` for ₹3,499 arrives. Torque
   matches it to the *merged set* (two cases sharing that one outreach action
   whose combined amount-at-risk is ₹3,499). It:
   - re-splits the outreach action's recovery credit: ~14% to the subscription
     case, ~86% to the invoice case (proportional to amount);
   - marks **both** cases **Recovered / Agent-Assisted** (Torque messaged them
     within 24h);
   - sets `recovered_amount` = ₹499 and ₹3,000 respectively, `closed_at = now`;
   - writes a `PAYMENT_RECONCILED` entry on each case's ledger;
   - removes nothing from the human queue (neither was escalated).

9. **Outcome.** ₹3,499 recovered, attributed to Torque, split fairly, fully
   audited — and it will count as *incremental* recovery if Priya's relationship
   with NorthPeak was in the treatment cohort (the measurement report is Module
   9).

*Counter-example (self-recovery):* if instead Torque had done nothing yet
(diagnosis still running) when Priya paid, reconciliation would find her
detection-stage case and close it **Cancelled / Self-Recovered** — no credit to
Torque. That honesty is the point.

---

## 8. Business Value

Torque is designed to move these outcomes (no invented numbers — these are the
levers, not measured results):

- **Recovered revenue** — declined payments, failed renewals, and overdue
  invoices that come back because Torque timed and framed the recovery correctly.
- **Reduced silent churn** — subscription/mandate failures caught and recovered
  before the customer is gone.
- **Reduced leakage per merchant** — a systematic process replaces an ad hoc one.
- **Reduced manual operations** — dunning, retry management, and cart recovery run
  themselves up to a bounded ceiling; humans only touch the cases worth touching.
- **Safer automation** — card-network fees avoided (no hammering dead cards), RBI
  / NPCI / WhatsApp rules enforced, sender reputation protected.
- **Higher recovery efficiency** — resource-aware prioritisation puts effort where
  the expected value is highest.
- **Less unnecessary customer contact** — the 4-hour quiet period, outreach merge,
  quiet hours, and live-conversation suspension cut message volume.
- **Credible reporting** — attributed (not gross) recovery, and an incrementality
  design that reports *lift* against a control with honest confidence intervals.
- **Audit readiness** — an append-only ledger and a prominent exception list of
  every blocked action.

---

## 9. What Makes Torque Different

**Implemented differentiators (you can demo these today):**

- **Compliance by construction.** Non-compliant automated actions are
  structurally blocked, not just discouraged — and every block is visible in an
  exception list. Card-network retry caps, RBI pre-debit notice (with self-heal),
  NPCI peak windows, WhatsApp consent + templates, live-conversation suspension.
- **One case object across all four legs.** Payment, checkout, subscription, and
  B2B share a record, an event ledger, and a customer view — including merging two
  signals of the same loss.
- **Root-cause diagnosis, not symptom reaction.** Classified failure reason with
  confidence, and honest routing of low-confidence cases to humans.
- **Coordinated, minimal outreach.** Cross-leg quiet period, merged messages,
  deferral instead of dropping.
- **Attributed recovery.** Agent-Assisted vs. Self-Recovered vs. Ambiguous —
  gross recovery numbers become defensible ones. The payment-link path is an
  unambiguous attribution signal.
- **Append-only, explainable audit** as the single history mechanism.

**Architectural / product differentiators (design choices that compound):**

- Resource-aware prioritisation by `(probability × amount) ÷ cost` everywhere —
  the same economics orders outreach and the human queue.
- Bounded, version-pinned playbooks — a hard cap on autonomy, stable mid-flight.
- Atomic action+audit writes and idempotent, tenant-scoped processing throughout
  — a money-grade backbone.
- Incrementality measurement designed in from day one (per-relationship cohorts).

**Future differentiators (designed, not built):**

- An ML recovery-scoring model (uplift modelling) replacing the cold-start
  lookup, with the feature store already shaped for it.
- Reported lift against a held-out control with confidence intervals and an
  honest cross-merchant spillover footnote.
- A merchant dashboard and agent console.

---

## 10. Product Vocabulary / Pitch Terminology

| Term | Say it as |
|---|---|
| **Revenue Leak Case** | "the one shared record for a single lost payment, used by every part of the system" |
| **Leg** | "which funnel the loss came from — payment, checkout, subscription, or B2B" |
| **Root cause / diagnosis confidence** | "why it failed, and how sure we are — low confidence goes to a human" |
| **Network directive** | "the card network's own instruction: retry-ok, retry-after-N-hours, dead-instrument, or do-not-retry" |
| **Playbook / Playbook Run** | "a short, pre-authored, bounded recovery sequence, and one execution of it" |
| **Guardrail / block / defer / self-heal** | "a compliance check before every action: block if unsafe, reschedule if badly timed, auto-fix if fixable" |
| **Compliance Guardrail Engine** | "the single place every automated action is checked, in a fixed order" |
| **Outreach Coordinator** | "cross-case contact discipline — quiet period, merged messages, deferral, live-conversation suspension" |
| **Escalation ceiling** | "the point where we stop automating and hand the case to a person" |
| **Human queue** | "the per-merchant, value-ordered list of cases that need a human" |
| **Reconciliation** | "matching an incoming payment back to the case that was leaking" |
| **Attribution** | "who caused the recovery — us, the customer, or ambiguous" |
| **Agent-Assisted / Self-Recovered / Ambiguous** | the three attribution outcomes |
| **Recovered / Partially Recovered / Cancelled / Exhausted / Escalated** | the five ways a case ends |
| **Systemic Event** | "a detected bank/network outage that pauses outreach" |
| **Incrementality / control cohort** | "measuring the revenue we actually *caused*, against a held-out group" |
| **CaseEvent ledger** | "the append-only, tamper-evident history and the 'why' explanation" |
| **Compliance by construction** | the headline positioning line |

---

## 11. Questions I Should Be Ready For

**Investor**

- *"Isn't this just a retry tool?"* — Retry is one action in one leg. Torque is
  the full closed loop across four legs — diagnosis, bounded compliant recovery,
  coordinated outreach, human escalation, and *attributed* reconciliation — on one
  case object. The moat is compliance-by-construction and honest attribution.
- *"What's the wedge?"* — Payment-degradation retry recovery for subscription
  businesses on Razorpay: a measurable, bleeding, recoverable number, with the
  cleanest attribution signal (Torque-generated payment links).
- *"How do you know it works?"* — Attribution (Agent-Assisted vs. Self-Recovered)
  plus a per-relationship control cohort for incremental lift. We report lift with
  confidence intervals, not vanity totals. (Measurement reporting is the next
  build.)
- *"Defensibility?"* — The compliance engine (a real barrier — card-network,
  RBI, NPCI, WhatsApp rules), the shared-case data model, and accumulating
  outcome data that feeds an uplift model.

**Customer**

- *"Will you spam my customers?"* — No. Quiet hours, a 4-hour cross-leg quiet
  period, merged messages, a suspension while a live chat is open, and a hard
  escalation ceiling. Every blocked message is visible to you.
- *"Will you get me fined by the card network / RBI?"* — The opposite. Retry
  budgets, do-not-retry directives, the mandatory 24-hour pre-debit notice
  (auto-inserted if missing), and NPCI peak windows are enforced before any
  action.
- *"What counts as recovered?"* — Only payments we can attribute. If a customer
  self-pays with no action from us, that's Self-Recovered and it doesn't count
  toward our number.
- *"What about partial payments on invoices?"* — Handled: the case stays open,
  the payment is applied oldest-invoice-first, and we keep chasing the balance.
- *"Data isolation?"* — Strict per-merchant scoping; customer PII stored once with
  DPDP-aligned erasure; an append-only audit trail.

**Technical / product**

- *"Idempotency / double delivery?"* — Every inbound event is de-duplicated on
  the provider's event id; reconciliation is a no-op on an already-processed
  event; a duplicate payment for a closed case matches nothing.
- *"Concurrency?"* — Case rows are locked during reconciliation so two workers
  can't double-close; execution timers are claimed with skip-locked semantics so a
  step never runs twice.
- *"Atomicity?"* — An action and its audit-ledger entry are written in one
  transaction — no action can exist without its history.
- *"Explainability?"* — The append-only ledger *is* the explanation; the "Agent
  Reasoning" panel renders it directly.

**Compliance / safety**

- *"WhatsApp rules?"* — Both gates: customer opt-in *and* an approved template of
  the right category; plus suspension during a live service conversation.
- *"RBI e-mandate?"* — The per-attempt 24-hour pre-debit notification is a hard
  gate; if it's missing, Torque auto-sends it and reschedules the retry rather
  than dead-ending.
- *"What if there's a bank outage?"* — Detected as a systemic event; outreach is
  suppressed and cases are held until it clears.

**"Why can't X already do this?"**

- *Payment gateways* do retries, not diagnosis + coordinated outreach +
  attribution across legs.
- *Dunning tools* do subscription emails, not payment-degradation retries, not B2B,
  not compliance budgets, not one case object.
- *Cart-recovery tools* do checkout only.
- *Doing it in-house* means rebuilding the compliance engine and the attribution
  logic — which is exactly the hard part.

---

## 12. Current Capabilities vs Future Roadmap

**Implemented now (demonstrable):**

- Verified, idempotent, multi-tenant ingestion across all four legs; self-recovery
  hold; cross-leg case merge; outage (network-wide) detection.
- Root-cause diagnosis with confidence and human routing.
- Bounded, version-pinned playbook selection and durable execution with
  payday-aware timing and allowed-hours deferral.
- The Compliance Guardrail Engine (all rules) with block / defer / self-heal.
- The Outreach Coordinator: 4-hour cross-leg quiet period, merged messages,
  deferral, live-conversation suspension.
- Escalation ceiling and the per-merchant human queue with three feeders.
- **Payment reconciliation & attribution** (Module 7): direct payment-link,
  indirect amount match with the 24-hour Agent-Assisted window, merged-set credit
  split, ambiguous handling, self-paid cancellation, B2B partial payments, and
  correct case closure with a full audit entry.
- Append-only audit ledger; strict tenant isolation; DPDP-aligned PII handling.

**Implemented but dependent on a future step:**

- The **direct payment-link attribution path** is fully built; it becomes
  end-to-end once the link-creation *action* is switched from stub to live
  delivery.
- The **Outreach Coordinator / human-queue priority** uses a placeholder
  (amount at risk) until the Module 8 score plugs into the same seam.

**Explicitly deferred (designed, out of demo scope):**

- Real outbound delivery (WhatsApp / email / SMS / retry / payment-link creation)
  — the execution layer is a safe stub today, so Torque fires nothing externally.
- The ML recovery-scoring model (uplift modelling) — the cold-start lookup and
  feature set are specified.
- Per-issuer outage detection (needs issuer data extraction).
- `WRITTEN_OFF` and the human agent console (a human *using* the queue) — Module
  10.
- The `LOG_PROMISE` action creating promise-to-pay records — the broken-promise
  routing hook exists and is tested.

**Future roadmap:**

- Module 8 scoring model; Module 9 reporting + incrementality lift with confidence
  intervals and the SUTVA cross-merchant footnote; Module 10 merchant dashboard,
  agent console, and demo surface; production infra; SMS at scale (TRAI DLT);
  card account updater.

**Never claim** a planned capability is available. Torque today is a complete,
audited *decision-and-bookkeeping* loop; it does not yet send real messages or
move real money, and it does not yet report measured lift.

---

## 13. Module 7 Additions

*(New or materially clarified product knowledge from this module.)*

**New capability: the loop is now closed.** Before Module 7, Torque could detect,
diagnose, plan, execute (in stub), and coordinate — but a payment coming back was
an unmatched mystery credit. Module 7 adds **reconciliation**: it takes a verified
payment-success signal and connects it to the exact Revenue Leak Case that was
leaking.

**New concept for the pitch: recovery attribution.** "Recovered revenue" is now a
*typed* outcome:

- **Agent-Assisted** — Torque acted on the case within the last 24 hours (or the
  payment came through a Torque-generated link). This is the number Torque takes
  credit for.
- **Self-Recovered** — the customer paid with no Torque action in the window, or
  paid before Torque even finished diagnosing. Torque does **not** take credit.
- **Ambiguous** — a payment matched more than one indistinguishable case; Torque
  attributes it to the most-recently-worked case and says so, rather than
  pretending certainty.

Talking point: *"Our recovered-revenue number is auditable because we can tell
you, case by case, whether we caused it."*

**New workflow: what "resolved" means operationally.** A case now ends in one of:

- **Recovered** — full amount matched; case closed with `recovered_amount` and a
  close timestamp.
- **Partially Recovered** (B2B only) — a partial payment landed; it's applied to
  the oldest invoice first, the case's amount-at-risk drops to the remaining
  balance, and the case **stays open** and keeps dunning. When the last balance
  clears, it becomes Recovered.
- **Cancelled / Self-Recovered** — the customer self-paid before Torque acted; the
  pre-playbook case is closed with no credit to Torque. *(This required adding two
  transitions to the case state machine — a customer can now self-pay out of the
  detection or diagnosis stage.)*

**New guarantee: duplicate financial events can't create duplicate recovery
outcomes.** Reconciliation is one transaction per event; a redelivered event does
nothing; two workers reconciling different payments for the same case can't both
close it (the case row is locked while it's being closed); a duplicate payment for
an already-closed case matches nothing. Talking point: *"If your provider sends us
the same 'paid' webhook three times, or two payments land for one case at once,
you get exactly one recovery, one audit entry, one number."*

**New behaviour: merged-outreach credit is settled fairly.** When Torque had
merged two cases into one message and a single payment settles both, it re-splits
the recovery credit proportionally to each case's amount at risk and closes both —
so a lump payment for "₹499 subscription + ₹3,000 invoice" is booked as ₹499 and
₹3,000 recovered, not ₹3,499 against a random one.

**New behaviour: reconciliation keeps the human queue honest.** If a payment lands
for a case that was sitting in the human queue, closing the case also removes it
from the queue — a human never opens a case that's already resolved.

**Business implication.** Module 7 is what makes Torque's core claim testable. The
recovered-revenue figure a merchant sees is now (a) matched to real cases, (b)
labelled by who caused it, (c) split fairly across merged work, and (d) fully
audited. Combined with the per-relationship control cohorts already in the data
model, it's the foundation for reporting *incremental* lift in the next module.

**What Module 7 did NOT do (be precise in a pitch):** it does not send anything,
it does not decide *write-offs* (that's a human decision in a later module), and
it does not yet report lift — it produces the clean, attributed, per-case data
that the reporting module will aggregate.

---

## 14. Module 8 Additions — Recovery Scoring

*(New product knowledge from this module. Pitch language, not implementation.)*

### What recovery scoring is

Every open Revenue Leak Case now carries a single number — a **recovery priority
score** — that answers one question: *if we can only chase some of these losses
right now, which ones are worth chasing first?*

The score is deliberately simple to say out loud:

> **(how likely we are to recover it) × (how much is at stake) ÷ (what the next
> nudge will cost us)**

A high score means "likely, large, and cheap to pursue." A low score means
"unlikely, small, or expensive to pursue." Torque works the queue in score
order.

### Why it matters — not every at-risk rupee deserves equal attention

A recovery agent has finite resources: message-sending budget, the free window
on a WhatsApp conversation, and — above all — human agents' time. Treating a
₹300 abandoned cart the same as a ₹60,000 failed annual subscription wastes all
three. Worse, a naive "biggest amount first" rule lets a large but nearly
un-recoverable debt (a 200-day-overdue invoice from a counterparty who never
pays) crowd out a smaller, fresh, highly recoverable one.

Recovery scoring makes the trade-off explicit and economic. It's the concrete
mechanism behind Torque's "resource-aware prioritisation" claim — the same
number orders both the automated outreach queue and the human escalation queue,
so the whole system pulls in one direction.

### The three inputs

**Probability — how likely is recovery?**
A benchmark percentage drawn from published industry recovery rates, chosen by
the *kind* of loss and *how old it is*:

| Situation | Benchmark recovery probability |
|---|---|
| Subscription/mandate failure, 0–48h old | 65% |
| Subscription/mandate failure, ~3–7 days old | 45% |
| Subscription/mandate failure, over a week old | 25% |
| Payment degradation, same session | 55% |
| Checkout abandonment, same session | 40% |
| B2B invoice, 0–30 days overdue | 35% |
| B2B invoice, 30–90 days overdue | 20% |
| B2B invoice, 90+ days overdue | 12% |

The pattern is intuitive: **fresh losses recover far better than stale ones**,
and the type of failure already tells you a lot (a mandate that failed an hour
ago is very different from a three-month-old receivable). These numbers are not
guesses Torque invented — they're the industry-benchmark starting point, applied
consistently.

**Amount at risk — how much is at stake?**
The rupee value the case would lose if nothing is recovered. For a bundled B2B
dunning thread it's the sum still outstanding across the invoices.

**Intervention cost — what will the next nudge cost?**
The expected cost of the *next* step Torque would take on this case — for
example, one WhatsApp message at its real per-message rate. This is
**forward-looking**: it's what the next action costs, not a tally of what's
already been spent. A case whose next step is a free payment retry is cheaper to
pursue than one whose next step is a paid message, and the score reflects that.
When the next step has no messaging cost, or the cost isn't known yet, Torque
uses a tiny floor value so a free-but-valuable case still ranks at the top —
without ever dividing by zero.

### The formula

> **score = probability × amount at risk ÷ expected next-step cost**

All of it in exact money arithmetic. The score is stored on the case and exposed
as a full breakdown, so any screen can show *why* a case ranks where it does —
not just the final number.

### Cold-start vs warm-start scoring

**Cold-start** is the benchmark-table lookup above: it works from day one, for a
brand-new merchant with zero history, because it only needs the loss type and
its age. This is the same "rule-based now, data collected from day one, learned
model later" philosophy Torque already uses for diagnosis — applied consistently
rather than pretending scoring is a different kind of problem.

**Warm-start** kicks in when Torque *does* have relationship history with that
customer for that merchant — specifically their **promise-keeping rate** (how
often, historically, they actually paid after saying they would). A strong
track record nudges the probability up; a poor one nudges it down.

### Promise-keeping history and why the adjustment is bounded

The warm-start adjustment is a **multiplier on the benchmark, capped between
0.5× and 1.3×**. A customer who always keeps promises can lift a case's
probability by at most 30%; one who never does can cut it in half — but no
further.

The cap matters. Without it, one case with rich history and its neighbour
without any would swing wildly apart on the strength of history alone, and the
queue order would lurch around for reasons that have nothing to do with the
actual opportunity. Capping keeps cold-start and warm-start cases on a
comparable scale, so the ranking stays stable and explainable. History
*informs* the score; it doesn't get to *dominate* it.

### How the score changes outreach priority

When two cases for the same customer are both due for a nudge, the
higher-scoring one leads — it owns the merged message, and its framing wins. The
message-sending order across the whole book follows the score. A large, fresh,
cheap-to-pursue loss gets contacted before a small, stale, expensive one, every
time, automatically.

### How the score changes human-escalation priority

The human queue is sorted by the **same** score. When an agent opens their
queue, the case at the top is the one where their time buys the most expected
recovery — not just the biggest number, and not first-in-first-out. As cases
age and their odds decay, the daily re-score quietly re-orders the queue so it
stays honest.

### A concrete example

> **Recovery Priority**
>
> | | |
> |---|---|
> | Probability | 0.65 |
> | Amount at risk | ₹12,400 |
> | Expected next-step cost | ₹0.885 (one WhatsApp message) |
> | **Priority score** | **≈ ₹9,107** |
>
> **Why:** Subscription failure · 0–48h old · 65% benchmark recovery
> probability · adjusted by relationship history · next intervention: WhatsApp

Read it as: *"a fresh subscription failure, ₹12,400 at stake, ~65% likely to
recover, and the next touch costs under a rupee — chase this now."* A
200-day-overdue ₹12,400 invoice with the same amount would score a fraction of
this, because its recovery probability is 12%, and it would sit far lower in
both queues.

### Business value

- **More recovered revenue per rupee spent and per agent-hour** — effort flows
  to where it pays off.
- **A defensible prioritisation story** — "why did you contact this customer
  before that one?" has a one-line, numeric, auditable answer.
- **Graceful cold start** — a new merchant gets sensible prioritisation on day
  one, with no historical data required.
- **It compounds with attribution** — Module 7 tells you which recoveries Torque
  caused; Module 8 makes sure Torque spends its effort where causing a recovery
  is most valuable.

### How this contributes to Torque's AI / decisioning story

Torque today uses **explainable recovery scoring** to prioritise economic
opportunities: a transparent formula over a benchmark probability, a bounded
relationship-history adjustment, and a forward-looking cost. Every number on the
screen can be traced to an input.

The **upgrade path** is deliberate and already designed for: once enough
resolved cases have accumulated (on the order of 500+), the benchmark lookup can
be replaced by a **learned recovery-prediction model**, and the average-effect
thinking by **individual uplift modelling** — predicting the recovery lift *for
this specific case* rather than for its category. The data those models need has
been collected since day one; no schema change is required to make the switch,
only a new consumer of existing data.

The pitch line: *"Torque currently uses explainable recovery scoring to
prioritise economic opportunities, with a clear path toward learned recovery
prediction as historical outcome data accumulates."*

### What is implemented today vs what future learned models would add

| Today (implemented) | Future (roadmap) |
|---|---|
| Benchmark recovery probability by loss type and age | Recovery probability predicted per case from its full feature set |
| One bounded multiplier from promise-keeping history | Individualised uplift — the recovery lift attributable to *acting* on this specific case |
| A transparent, hand-checkable formula | A model with per-feature explanations (which factors drove this score) |
| Recomputed on case creation, on diagnosis, and daily | Continuous / event-driven re-scoring |

The current model is intentionally not a black box — for a hackathon and an
early customer, "here is exactly why" beats "trust the model."

### Likely investor / customer questions — and concise answers

- **"Where do the probability numbers come from?"** Published industry recovery
  benchmarks, keyed by failure type and age. They're the starting point every
  serious recovery operation uses; we apply them consistently and collect the
  outcome data to calibrate them.
- **"Isn't a fixed table crude?"** For prioritisation at this stage, a
  transparent table that everyone can sanity-check beats an uncalibrated model.
  The table is a floor, not a ceiling — the learned model is a data-threshold
  away, and the pipeline for it already exists.
- **"Why cap the history adjustment?"** So relationship history informs the
  ranking without destabilising it. A customer's track record can move a case by
  at most +30% / −50%; it can't let a data-rich case leapfrog a data-poor one
  purely because it has more history.
- **"What if the cost is zero or unknown?"** The score uses a tiny floor so it
  stays finite and comparable. A genuinely free next step (a payment retry) then
  ranks at the very top — which is the correct call: free, likely, and valuable
  is exactly what you want to chase first.
- **"Does bigger amount always win?"** No. Amount is one of three factors. A
  huge but near-hopeless or expensive-to-pursue case will lose to a smaller,
  fresh, cheap one — which is the entire point.
- **"How often does the score update?"** On case creation, again when diagnosis
  finishes (the odds and the likely next step firm up), and once a day for every
  open case so aging is reflected.
- **"Is the same score used everywhere?"** Yes — one number, one definition,
  driving both the automated outreach order and the human queue. There is no
  competing ad-hoc ranking anywhere in the system.

### What Module 8 did NOT do (be precise in a pitch)

It does not send anything, it does not build the merchant dashboard or the agent
console, and it does not add a learned model. It computes and exposes the
priority number, keeps it fresh, and wires it into the two places that already
needed it.
