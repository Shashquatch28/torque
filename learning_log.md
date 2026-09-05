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
- **Status:** implemented, now on the full Module 8 score (probability ×
  amount at risk ÷ expected next-step cost) — the seam this section originally
  flagged as a placeholder is live as of Module 8.

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
- **Recovery scoring** (Module 8): `(probability × amount at risk) ÷ expected
  next-step cost`, cold-start benchmark + bounded warm-start promise-keeping
  adjustment, live on both the Outreach Coordinator and the human queue — the
  placeholder this section once flagged is fully retired.

**Implemented but dependent on a future step:**

- The **direct payment-link attribution path** is fully built; it becomes
  end-to-end once the link-creation *action* is switched from stub to live
  delivery.

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

---

## 15. Module 9 Additions — Recovery Measurement & Reporting

*(New product knowledge from this module. Pitch language, not implementation.)*

### Why recovery measurement matters

Everything before Module 9 was Torque *doing the work* — detecting leaks,
diagnosing them, running playbooks, staying compliant, matching payments back to
cases, prioritising by economic value. Module 9 is Torque **proving it worked**.

A merchant's first question is never "how many messages did you send?" It is
**"how much money did I get back, and would I have gotten it anyway?"** Module 9
answers the first half rigorously and is honest about the second.

### Revenue at risk vs revenue recovered — the two numbers that matter

- **Revenue at risk** — the total rupee value of everything that was leaking in
  the period: failed subscription charges, abandoned carts, degraded payments,
  overdue invoices. This is the size of the problem.
- **Revenue recovered** — of that, how much actually came back **because of
  Torque**. Not "a payment eventually landed" — *Torque caused it* (it acted on
  the case within the attribution window, or the payment came through a
  Torque-generated link).

The gap between the two is the opportunity that remains. The ratio is the
recovery rate.

### How Torque measures recovery

Recovery is grounded in the **reconciliation outcome** already recorded on each
case (from the payment-attribution module), not re-derived. Every recovered case
carries:

- **how much** came back,
- **who caused it** — *Agent-Assisted* (Torque), *Self-Recovered* (the customer
  paid on their own), or *Ambiguous* (a payment matched more than one case and
  Torque won't pretend certainty).

The headline "recovered" figure counts **only** Agent-Assisted and Ambiguous.
Self-Recovered money is shown **separately, next to it** — never folded in. A
merchant sees exactly what Torque can and cannot take credit for.

### Why "messages sent" is not the success metric

Message volume, retry counts, playbooks started, AI recommendations made — these
are **activity**, not outcome. A system optimised to send more messages is
optimised for the wrong thing. Torque's north-star is **revenue recovered**;
operational activity is *supporting evidence* that explains how the recovery
happened, and it lives in a separate part of the report. Confusing the two is
how recovery vendors end up billing for effort instead of results.

### How recovery is attributed to interventions

The report breaks recovered money down two ways:

- **By leg** — payment retry, checkout abandonment, subscription/mandate,
  B2B receivables. The primary view: for each leg, how many cases, how many
  recovered, how much was at stake, how much came back, and the rate.
- **By intervention type** — the kind of action Torque executed (a payment
  retry, a WhatsApp/email/SMS nudge, a payment link). A case that used more than
  one shows up under each, so a merchant can see which *tactics* pull their
  weight.

Attribution itself is not recomputed here — Torque reuses the per-case decision
the reconciliation module already made, including the proportional credit split
when one payment settled two merged cases.

### What a merchant sees in a recovery report

```text
TORQUE RECOVERY REPORT

Cases analysed              1,000
Revenue at risk          ₹1.20 Cr

Recovered (Torque)        ₹52.4 L
Self-recovered            ₹11.0 L        (shown, not counted)
Recovery rate                 43.7%      (by amount)   |   46.3% (by cases)

Recovered cases                463
Unresolved cases               412        (₹41.2 L still at risk)
Human escalations               58
Blocked                         31        (₹6.1 L — deliberate, by rule)
Deferred                        44

Recovery by leg
  Subscription/mandate    ₹21.4 L        61% recovery rate
  Payment retry           ₹18.2 L        54%
  B2B receivables          ₹9.7 L        38%
  Checkout abandonment     ₹3.1 L        29%

Where Torque deliberately did NOT act
  Network hard-stop (do not retry)        18 actions
  No customer consent on file             9
  Quiet hours / bad timing                (deferred, retried later)
```

Two halves: **what recovered money** (top), and **where Torque deliberately
stopped or escalated** (bottom). The second half is as important as the first —
it is the "compliance by construction" story made visible: Torque didn't fail to
act on those cases, it *chose* not to, by rule.

And every number drills down: a merchant can go from a leg → the cases → one
case → the full, plain-language history of what the agent did and why (the same
event stream that is the audit trail).

### How batch-level measurement proves the product's value

Run Torque over a batch of a merchant's revenue-at-risk cases and the report
gives a single, defensible answer: *"of ₹X at risk, Torque recovered ₹Y, at a
Z% rate, and here is the case-by-case evidence."* That is the pitch — not a
capability demo, a **measured result** on the merchant's own data, with the
methodology (what counts as "recovered", who gets credit) stated openly.

### Useful merchant questions Torque can now answer

- "How much of my failed-subscription revenue did you actually recover last
  month?"
- "Which leg is worth the most to me — where should I turn Torque up?"
- "Show me every case you escalated to a human, and why."
- "How much revenue is still at risk right now, and in which cases?"
- "Where did you choose not to contact a customer, and on what rule?"
- "For this specific recovered payment — what did you do, and do you take
  credit?"

### How this supports the Track 03 hackathon requirement

Track 03 asks for a system that identifies revenue at risk **and** shows what it
did about it. Module 9 is the "shows what it did" half: it turns the whole
pipeline's output into a merchant-facing, evidence-backed recovery report, with
the honest-reporting posture (self-recovered shown separately, exceptions
surfaced prominently) built in rather than bolted on.

### Descriptive reporting vs causal / incrementality measurement

Two different claims:

- **Descriptive** — "here is what happened: ₹Y recovered, on these cases, by
  these interventions." Module 9 does this, rigorously.
- **Causal / incremental** — "here is the recovery **lift** Torque produced
  versus a held-out control group that got nothing, with a confidence interval."
  A separate, later capability.

Torque's data model already assigns every merchant-customer relationship to
treatment or a held-out control, so the causal measurement is a formula away —
but it is **not** in Module 9. Module 9 does not claim to prove Torque *caused*
the recovery beyond the per-case attribution; it reports what occurred.

### What Module 9 implements now

The full descriptive report: revenue at risk, recovered (Torque-credited),
recovery rate (by amount and by case count), unresolved / blocked / deferred /
escalated, breakdowns by leg / intervention / outcome / time, the operational
exception report, and case-level drill-down down to the agent's reasoning
stream. Read-only, per-merchant, and computed live from the system's own records
— there is no separate "reporting database" that could drift from the truth.

### What later causal / experimental reporting would add

- **Incrementality lift** — treatment recovery rate minus control recovery rate,
  so the merchant sees the recovery that would *not* have happened without
  Torque.
- **A confidence interval** on that lift — honest about small-sample uncertainty
  rather than a false-precision point number.
- **A spillover caveat** — flagging the specific B2B cross-merchant cases where a
  control result may have been contaminated by Torque's outreach for a
  *different* merchant, and reporting the adjusted figure alongside the headline.

### Likely investor / customer questions — and concise answers

- **"How do you define 'recovered'?"** Money that came back **and** that our
  attribution model credits to a Torque action (or a Torque payment link). If
  the customer paid on their own, we show it — separately — and don't count it.
- **"So you can't prove you caused it?"** Per case, we can — we know whether we
  acted, and how, before the money landed. Across the book, the *incremental*
  lift versus a control group is a separate report on the roadmap; the data for
  it is already being collected.
- **"Isn't 'messages sent' easier to report?"** Easier and useless. We report
  the outcome — rupees recovered — and keep the activity as the explanation, not
  the headline.
- **"What about the cases you didn't recover?"** They're in the report:
  unresolved (with the rupees still at risk), exhausted, escalated to a human,
  or deliberately blocked by a compliance rule — each broken out, not hidden.
- **"Can I trust the numbers?"** Every figure derives live from the case,
  action, and payment records, and drills down to the individual case and its
  full event history. There is no separate rollup table to reconcile.
- **"Is one merchant's data ever visible to another?"** No — every query is
  scoped to the merchant, end to end, and that is tested exhaustively.

### What Module 9 did NOT do (be precise in a pitch)

It does not build the dashboard UI (that consumes these numbers — next module),
it does not compute incrementality lift or confidence intervals (a later causal
report), and it does not re-run payment matching (it reads the attribution the
reconciliation module already made). It is the measurement layer: honest,
outcome-based, and fully auditable.


---

## 16. Module 10 Additions — The Product Surface

*(New product knowledge from this module. Pitch language, not implementation.)*

### Why this makes Torque more than a backend

Before Module 10, Torque was a working recovery engine you had to take on
faith — the intelligence was real but invisible. Module 10 is where a merchant
or a judge can **open Torque, see it working, and understand it in under a
minute** without reading a line of code. It turns the pipeline into a product:
one command starts everything, one screen tells the story.

### What the merchant dashboard tells a customer

At a glance, in order of importance:

- **Revenue recovered by Torque** — the big number, front and centre. Money that
  actually came back because Torque acted.
- **Revenue at risk** — the size of the leak Torque is working on.
- **Recovery rate** — recovered as a share of at-risk.
- **Recovered cases / unresolved cases / human escalations** — the operational
  picture.
- **Blocked and deferred (by rule)** — money Torque deliberately did not chase
  yet, because a compliance rule said so. Shown as restraint, never as failure.
- **Cost efficiency** — recovered rupees per rupee spent.

Below the headline: recovery broken down by leg (subscription, payment, checkout,
B2B), a simple recovery-over-time chart, a ranked top at-risk cases list, and —
prominently, not buried — the exception list: every place Torque held back and
why.

### What "revenue at risk" and "revenue recovered" mean, on screen

- **Revenue at risk** is the total value of the failed payments, abandoned carts
  and overdue invoices Torque has taken on.
- **Revenue recovered** is the subset of that which came back and which Torque's
  attribution model credits to a Torque action. Money the customer paid on their
  own is shown next to it, labelled "self-recovered — not counted".

The dashboard never implies that messages sent, retries attempted, or AI
recommendations made are the same as money recovered. The north-star is the
recovered figure; everything else is supporting evidence.

### How the merchant sees Torque prioritising cases

The "top at-risk cases" list is ordered by Torque's recovery priority score —
likelihood of recovery, size of the exposure, and the cost of the next nudge,
combined. The merchant sees which cases Torque is working first, and can click
any one to see why it ranks where it does. The ordering is Torque's decision,
shown honestly — the screen does not re-rank anything itself.

### How the explainability console answers "why did Torque do this?"

Open any case and two things appear:

1. **"Why this case?"** — the priority calculation laid out plainly: recovery
   probability, amount at risk, expected intervention cost, and the resulting
   priority score, with a short plain-English "why" (for example: Subscription
   failure, 0–48h old, 65% benchmark recovery probability, next intervention:
   WhatsApp).
2. **The audit trail** — a chronological timeline of everything Torque did on the
   case: risk detected, diagnosis with confidence, intervention selected,
   guardrails checked, action executed, payment reconciled, money recovered.
   Each step is the agent's own recorded reasoning. This is the primary answer to
   "why did the agent do this?" — and it is a query over the existing history,
   not a story reconstructed after the fact.

### How the human agent takes over

Some cases route to a person: a low-confidence diagnosis, a broken promise to
pay, an automation that hit its ceiling. The Agent Console shows that queue,
ordered by the same economic priority as everything else. For any case a human
can:

- pause it (take it out of automated playbook execution) and un-pause it (hand it
  back);
- resolve it — mark it recovered (with the amount), partially recovered, or
  written off.

A resolution is recorded as a first-class outcome: the case closes, the recovered
amount is booked, an audit entry is written naming the agent, and the case leaves
the queue. The dashboard reflects it immediately.

### Why manual controls are important

Automation that cannot be overridden is a liability. The console proves Torque is
operable: a merchant's team keeps final say on the hard cases, every human action
is audited exactly like an automated one, and "the agent gave up" is a visible,
deliberate state (written off) rather than a case that silently rots.

### How the live demo proves the system is actually working

The Live Demo view has a button per synthetic scenario and a feed that updates
every few seconds. Click "Payment failure" and a new case appears in the feed and
flows through detection and diagnosis. Click "Network hard-stop" and a case
appears, reaches the playbook stage, and then a guardrail blocks the retry —
visibly, with the reason. A judge watches cases move through states in real time
and understands the architecture without a walkthrough.

Crucially, the scenario buttons run the real ingestion and the real compliance
checks — nothing is faked. The "restraint" scenarios genuinely trip the guardrail
predicate before the block is recorded.

### How the exception list demonstrates restraint

The dashboard's "Where Torque deliberately held back" panel lists, by reason,
every action a guardrail blocked or deferred and the revenue it is holding:
network hard-stops, missing consent, retry caps, quiet-hours deferrals. This is
the compliance-by-construction differentiator made visible — Torque is not an
aggressive recovery bot that blasts every customer; it is a system that knows
when not to act, and shows you.

### What the product demo looks like from beginning to end

1. Start the server (one command). Open the dashboard.
2. See the headline: revenue recovered against revenue at risk, and the recovery
   rate.
3. Open the top at-risk case, read why Torque prioritised it, scroll its audit
   trail from "risk detected" to "money recovered".
4. Open the Agent Console, see the human queue, resolve an escalated case, watch
   the recovered number tick up.
5. Open Live Demo, inject a payment failure, watch it enter the feed; inject a
   network hard-stop, watch Torque refuse the retry and log why.
6. Back to the dashboard: the exception list now shows the block; the numbers
   have moved. Every figure came from real records.

### Likely customer / investor questions — and concise answers

- "Is this a real UI or a mock?" Real. It reads the live backend on every load;
  there are no hard-coded numbers anywhere in it.
- "Can my team actually operate it?" Yes — the Agent Console gives a human final
  say on escalated cases (pause / resolve / write-off), and every human action is
  audited exactly like an automated one.
- "How do I know Torque will not spam my customers?" The exception list is on the
  dashboard, not hidden — it shows every time a compliance rule stopped or
  delayed an action, and why.
- "How do you demo without live traffic?" One-click synthetic scenarios that run
  the real ingestion and the real guardrail checks — including scenarios where
  Torque deliberately does nothing.
- "What does the priority score mean?" It is a ranking number — likelihood times
  amount divided by next-step cost — not a rupee figure. Higher means chase this
  first.
- "Is any of the intelligence in the frontend?" None. The UI fetches, formats and
  displays; every metric, score and ranking is computed by the backend.

### What is implemented now

A merchant dashboard, a case-explainability view with the full audit timeline, an
Agent Console with working human overrides, a live demo surface with one-click
synthetic scenarios and a polling activity feed, and a deterministic seed so the
product never opens empty — all served by the same process on one port.

### What remains for later modules

- Real-time push (the live feed polls today);
- incrementality / lift reporting on the dashboard (a later causal-measurement
  module);
- production infrastructure (Module 11);
- a scripted judged-demo narrative (Module 13).

---

## 17. Modules 9b, 11 & 12/12a — Causal Measurement, Infra, and the Autonomous Loop

*(New product knowledge from these modules. Pitch language, not
implementation.)*

### The causal story: proving lift, not just totals (Module 9b)

Module 9's recovered-revenue number is honest but **descriptive** — it says
what happened. Module 9b adds the **causal** claim a sophisticated investor
or judge will actually ask for: *"how much of that would have come back
anyway?"*

Every merchant-customer relationship is assigned, from day one, to a
treatment cohort or a held-out control cohort. Module 9b computes each
cohort's recovery rate, the **incremental lift** between them (treatment
minus control), and a **95% confidence interval** on that lift using a
Wilson/Newcombe method appropriate for small samples — never a bare point
estimate presented as certain. It also computes a **SUTVA-adjusted**
version of the lift: because Torque operates across merchants, a "control"
customer at one merchant can still be a "treatment" customer at another and
self-recover from that unrelated outreach's spillover, quietly inflating
the apparent control rate. Module 9b detects and removes those contaminated
control counterparties and reports the adjusted lift **alongside**, never
instead of, the headline number.

**The pitch line:** *"We don't just tell you what we recovered — we tell you
what we caused, with a confidence interval, and we've already accounted for
the one methodological trap (cross-merchant spillover) that would make the
number look better than it is."*

### A reproducible runtime, not a laptop demo (Module 11)

Module 11 packages the entire system — Postgres, Redis, the API, the Celery
worker, the Celery beat scheduler — as one `docker-compose` stack, one
`Dockerfile` reused across all three application processes, built entirely
on free/self-hostable infrastructure. `docker compose --profile full up
--build` is the whole "run Torque" instruction for anyone, on any machine,
with no cloud account and no paid service.

**The pitch line:** *"This isn't a demo that only works on my laptop — it's
a reproducible runtime anyone can stand up in one command."*

### The loop closes itself (Module 12 / 12a)

Through Module 11, every stage of the pipeline worked, but something still
had to call the next stage — diagnosis, playbook activation, and execution
scheduling were each reachable, not each other's natural consequence.
Module 12a removes that seam: **a case created by any of the four ingestion
legs now flows autonomously** from detection through diagnosis, playbook
activation, and its first scheduled execution step, with no manual trigger
anywhere in between. A real webhook creating a case today is, within a
couple of seconds, diagnosed and (if confident) already working — the same
autonomy the Live Demo's scenario buttons now exercise directly.

**The pitch line:** *"Torque doesn't need an operator to keep clicking
'next' — a real failure signal runs the entire pipeline by itself, end to
end, the moment it arrives."*

---

## 18. The AI Layer — Explainable, Evidence-Grounded Decision Support

*(New product knowledge from Phases 0–8. Pitch language, not implementation.
This is the newest and most hackathon-relevant capability — read this
section closely before an AI/ML-focused judge conversation.)*

### What problem the AI layer solves

Everything through Module 12a is Torque *deciding and acting* — correctly,
but opaquely to anyone who isn't reading the audit trail line by line. A
judge, a new operator, or a merchant's ops lead doesn't want to read forty
`CaseEvent` rows to understand one case. The AI layer's job is narrow and
specific: **read the same evidence a human could read, and explain it in
plain language, with every claim traceable back to a real record.**

### The one rule that makes this safe: AI cannot decide anything

This is the single most important design fact about the AI layer, and it is
enforced in code, not just in a design doc: the AI package
(`torque.ai`) has a **structurally forbidden import boundary** — it
physically cannot import the state machine, the execution engine, or
anything capable of writing case state. A dedicated test fails the build if
that boundary is ever crossed. Every AI-facing route is read-only. The AI
layer can describe a decision Torque already made; it cannot make one.

**The pitch line:** *"Our AI can't act, even if it wanted to — the boundary
is enforced by the build, not by a policy someone could forget."*

### From raw history to a trustworthy narrative — five phases

1. **Evidence gathering** — the same case snapshot, timeline, actions,
   promises, and (aggregate, PII-free) customer-relationship signal a human
   reviewer would see, gathered read-only.
2. **Citation model** — every one of those evidence items gets a stable,
   referenceable id.
3. **Precedent retrieval** — has a comparable case, for this same merchant,
   happened before, and how did it resolve? Answered with real full-text
   search over the merchant's own resolved cases — never a fabricated
   "similar case," and an honest "none yet" when nothing comparable exists.
4. **Narrative generation** — an on-demand (never automatic, never polled)
   citation-grounded explanation: a summary, a claim about the current
   state, a claim about the root cause, a claim per timeline entry, each
   claim carrying the citation ids that support it.
5. **Citation validation** — after generation, every citation the model used
   is checked against the evidence it was actually given. **If even one
   citation doesn't resolve, the entire narrative is thrown away** — never
   partially trusted, never silently repaired.

### Why the provider is a deterministic mock, and why that's a deliberate choice

The AI layer's only concrete provider today is a fully deterministic,
offline, zero-API-key mock — not because a real LLM couldn't be wired in,
but because doing so is a paid-API-budget decision explicitly deferred, and
because a deterministic provider makes the citation-validation guarantee
*provable in a test*, not just an expectation of a live model's behavior.
The swap point is exactly one function; nothing else in the system knows or
cares which provider answered.

**The pitch line:** *"The architecture is provider-agnostic today by
design — the demo runs on a free, deterministic engine so every test is
reproducible; production would point the same one function at a real
model."*

### Honesty as a design constraint, not an afterthought

Three things are deliberately **not** shown anywhere in the product, on
purpose:

- **A fabricated confidence score.** The system does not claim "94%
  confident" about anything the underlying models don't actually produce.
- **The evaluation harness's own metrics.** A deterministic faithfulness/
  citation-coverage evaluator exists (Phase 5) — but it's a test/offline
  tool that watches the AI layer, not a number the AI layer gets to show
  off about itself in the product.
- **The shadow ML model's predictions.** An observational classifier (Phase
  7) was built to explore whether a learned model *could* add signal — but
  it has no API route, no UI, and no effect on any real decision. It
  exists to be measured against reality later, not to be shown today.

**The pitch line:** *"We built the measurement tools before we built
anything worth measuring optimistically — and we're showing you the
decisioning, not the lab experiments."*

### How a reviewer actually experiences this

Open any case, click "Explain this case," read the narrative, click any
citation chip — the exact evidence it points to (a timeline event, or the
case's own header) highlights on screen. That loop — claim, click,
verify — **is** the AI layer's whole value proposition, demonstrated in
under ten seconds, not asserted in a slide.

### Likely judge questions — and concise answers

- **"Is this just a chatbot bolted onto a dashboard?"** No — there is no
  conversational input anywhere. One button, one case, one grounded
  explanation. The interaction model is "ask this specific case a specific
  question," never a freeform chat.
- **"What happens if the model hallucinates a citation?"** The narrative is
  rejected outright, server-side, before it's ever returned to the browser
  — not repaired, not partially shown.
- **"Does the AI ever change what Torque does?"** No — architecturally
  impossible, not merely disallowed by convention.
- **"Why not a real LLM?"** A budget/API-key decision, explicitly deferred,
  with the exact one-function seam already built for it.
- **"What's actually novel here versus a RAG demo?"** The evidence, the
  precedent retrieval, and the citation model are all built on Torque's own
  case data — there is no separate knowledge base; the "documents" being
  retrieved are the merchant's own resolved cases.

### What the AI layer did NOT do (be precise in a pitch)

It does not diagnose a case, does not select a playbook, does not decide an
action, does not score anything that feeds the human queue or the
Outreach Coordinator, and does not report a confidence number the backend
doesn't actually compute. It explains decisions Torque already made
through the deterministic pipeline described in sections 1–17 above.
