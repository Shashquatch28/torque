# DEFERRED WORK REGISTER

Work that is **deliberately not built yet**. If you are about to implement
something here, STOP — it belongs to a future milestone and must be an explicit,
approved proposal first. Presence in this list is not a bug or an oversight; it
is a scoping decision.

Remove an item **only** when it is actually implemented (and record that in
`MILESTONES.md`). Organized by owning module.

Legend: 🔧 build (planned) · 📋 design-only for demo · 🔮 roadmap / out of demo scope.

---

## Build Roadmap Priority Classification (Module 12)

**Read this section first if you are deciding what to build next.** The
per-module lists below this point are the historical, chronological record —
what each module deferred and why, in the order the modules were built. This
section is the *current* cross-cutting view: every item still open anywhere
below, sorted by **what a judge needs to see live** rather than by which
module happened to defer it.

**The test applied to every item** (D-136): *does this materially strengthen
one of the five locked differentiators — root-cause diagnosis, one case
object/one ledger, incrementality-aware measurement, compliance-by-
construction, resource-aware prioritization — as something watchable, not
just readable?* Mentioning a feature in the blueprint is not, by itself, a
reason to build it before judging.

Four categories:

- **A — DEMO-CRITICAL.** Without it, a live demo cannot credibly show one of
  the five differentiators happening.
- **B — DEMO-ENHANCING.** Strengthens a live demo beat the blueprint's Module
  13 script explicitly names, but the demo already has a credible fallback
  (a static, fully-explorable seeded case, or a scripted-but-real code path)
  without it.
- **C — PRODUCTION-HARDENING.** Needed for Torque to work as a real,
  unattended product; irrelevant to what a judge watches.
- **D — FUTURE / OPTIONAL.** Blocked on data volume, an external/regulatory
  dependency, or genuinely out of scope; do not schedule.

Already verified **sufficient, no action** (do not rebuild): Module 9
descriptive reporting, Module 9b incrementality (API + dashboard card both
live), Module 10 Agent Console, Module 11 infra (`docker compose --profile
full` = db+redis+api+worker+beat, `/health/ready`, no Temporal), and the
compliance-guardrail demonstration itself — the three Decision-K restraint
scenarios (`hard_stop_mac` / `upi_retry_cap` / `nach_ceiling`) already drive
real ingestion → real diagnosis (`transition_case`, a real `DIAGNOSIS_COMPLETED`
event) → a real compliance-predicate assertion → a real `BLOCKED_BY_GUARDRAIL`
action, live, on demand (`src/torque/demo/scenarios.py`).

### A — DEMO-CRITICAL

**A1. Wire the ingestion → diagnosis → policy-activation → execution
auto-dispatch chain** (resolves D-080 / D-088 / D-093 — the three inter-module
triggers every module since Module 3 has deferred to "an orchestration-layer
concern").
- **Current state:** `torque.diagnosis.diagnose_case_task`,
  `torque.policy.activate_case_task`, and `torque.execution.schedule_run` are
  each complete, tested, and independently callable — but nothing calls them
  in sequence. A case created by real ingestion (or the `payment_failure` /
  `checkout_abandonment` demo scenarios) sits at `DETECTED` forever unless
  something external invokes `diagnose_case_task` by hand.
  `tests/test_module10_demo.py` asserts exactly this today
  (`status == "DETECTED"` for those two scenario keys) — not a bug, the
  documented current behaviour.
- **Why it matters:** this is the one place where "one autonomous agent" is
  still assembled by hand rather than actually autonomous — in the demo *and*
  in a real deployment. The Decision-K restraint scenarios and the static
  16-case seed already prove diagnosis + compliance + one-ledger work
  correctly; what's missing is the system doing it *on its own* when a case
  is created, which is the more honest and more impressive thing to show.
- **Dependency:** none. Every consumed engine (Module 3 diagnosis, Module 4
  policy, Module 5 scheduler) is complete and independently tested.
- **Priority:** 1 (highest of everything in this document).
- **Complexity:** LOW–MEDIUM — add `diagnose_case_task.apply_async(...)` after
  each of the four ingestion case-creation paths
  (`ingestion.{cases,checkout,subscription,b2b}`), `activate_case_task
  .apply_async(...)` after `DiagnosisOutcome.ROUTED_TO_PLAYBOOK`, and
  `schedule_run(...)` after `ActivationOutcome.RUN_CREATED`. No new domain
  logic — pure wiring at existing extension points, plus tests for the new
  call sites and one Celery-eager end-to-end test (webhook in → case fully
  worked or escalated, with no manual step).
- **Data model change:** no. **State machine change:** no (drives only
  already-legal transitions the engines already produce).
  **External services:** no.
- **Recommended ordering:** first — before Module 13, and before any item
  below.

### B — DEMO-ENHANCING

**B1. Live cross-leg-merge and B2B multi-invoice-bundle demo scenarios.**
- **Current state:** the real code is complete and tested
  (`ingestion.dedup.find_supersedable_case` / `find_supersedable_payment_case`
  — the bidirectional §2.4 merge; `ingestion.b2b.ingest_invoice`'s bundling
  rule), but `DEMO_SCENARIOS` has no entry that triggers either live — only
  the static seed shows a B2B case with 2 invoices, and no seeded case shows a
  cross-leg merge at all.
- **Why it matters:** the blueprint's own Module 13 script names this
  explicitly as a **"Live:"** beat ("a B2B multi-invoice bundle, and a merged
  cross-leg outreach event... shown rather than described") — directly
  strengthens differentiator 2 (one case object, one ledger, across all four
  legs). Not critical: a judge can already open the seeded B2B case and its
  real `CaseEvent` stream, which is a credible (if static) substitute.
- **Dependency:** none; independent of A1.
- **Priority:** 2.
- **Complexity:** LOW — two new `DEMO_SCENARIOS` entries + `inject_scenario`
  branches, mirroring the five existing ones; no new domain code.
- **Data model / state machine / external services:** no / no / no.
- **Recommended ordering:** alongside or immediately after A1, before Module 13.

**B2. Inline-diagnose the `payment_failure` / `checkout_abandonment` scenarios
(fallback only if A1 is skipped).**
- **Current state:** they stop at `DETECTED` (see A1).
- **Why it matters:** a lower-risk, demo-scope-only patch — mirrors the
  `_diagnose_to_playbook` helper the restraint scenarios already use — for a
  maintainer who wants a live "it diagnoses" beat without touching the
  production dispatch path right before judging.
- **Dependency:** none; **redundant once A1 is done** (A1 makes this
  unnecessary — do not build both).
- **Priority:** 3, and only relevant if A1 is explicitly deferred.
- **Complexity:** LOW. **Data model / state machine / external services:**
  no / no / no.

**B3. A larger/second incrementality demo cohort (tighter confidence interval)
— optional polish.**
- **Current state:** 3 control / 13 treatment gives an honest but wide lift CI
  (roughly ±45 points) — correct behaviour at this sample size (Blueprint
  §9.3: showing a wide interval openly is itself part of the honesty
  differentiator), not a defect.
- **Why it matters:** marginal; a tighter interval reads more "impressive" but
  the wide one is arguably the better demo of intellectual honesty.
- **Dependency:** none. **Priority:** 4 (lowest in B).
- **Complexity:** LOW (seed data only). **Data model / state machine /
  external services:** no / no / no.

### C — PRODUCTION-HARDENING (roadmapped only — do not implement before Module 13)

**C1. Real channel adapters** (§5.4 — Meta WhatsApp Cloud API, Resend, Fast2SMS,
Razorpay retry / Mandate-Execute / NACH re-presentment).
- **Current state:** `execution.executor.run_action` is a stub — always
  returns `SUCCESS`, no external I/O.
- **Why it matters:** required for Torque to do anything in a real deployment;
  not required to prove a differentiator to a judge (a verifiable-live WhatsApp
  send is not achievable in a demo room anyway — the guardrail *block* is the
  more demonstrable story, and it already works).
- **Dependency:** logically downstream of **A1** — without auto-dispatch, no
  `scheduled_job` is ever armed on live traffic, so `run_action` is never
  invoked outside a test or a demo scenario in the first place. Also needs
  live developer/test-tier credentials for 4 separate services (an
  operational dependency, not code).
- **Priority:** 5. **Complexity:** HIGH (4 distinct integrations + retry/error
  mapping + secrets).
- **Data model:** no (channel/cost columns already exist). **State machine:**
  no. **External services:** **yes** — Meta, Resend, Fast2SMS, Razorpay.

**C2. `GENERATE_PAYMENT_LINK` / `LOG_PROMISE` real execution.**
- **Current state:** stubbed alongside C1; Module 7 can still reconcile an
  externally-created `PaymentLink`, but execution never creates one.
- **Why it matters:** completes the recovery-signal loop for real traffic.
- **Dependency:** same tier as C1 (Razorpay Payment Links API).
- **Priority:** 5 (bundle with C1). **Complexity:** MEDIUM.
- **Data model / state machine:** no / no. **External services:** yes (Razorpay).

**C3. `Action.cost` population from real sends.**
- **Current state:** nullable, ~0 everywhere; Module 8's *forward* cost
  estimate (which reads `ChannelRateCard` directly) is unaffected — this is
  only Module 9's *backward-looking* `total_action_cost` / `cost_efficiency_ratio`.
- **Why it matters:** makes the descriptive cost-efficiency number real.
- **Dependency:** C1 (needs real sends to cost). **Priority:** 6.
- **Complexity:** LOW once C1 exists. **Data model / state machine:** no / no.
  **External services:** inherits C1's.

**C4. Issuer/BIN extraction (U-08) → §5.3 MAC first-touch lookup (D-083) →
`ISSUER_SPECIFIC` systemic detection.**
- **Current state:** both downstream items are blocked on the same genuinely
  **unresolved design question** (U-08: which field, extracted from where,
  stored on which model) — not merely unimplemented. `NETWORK_WIDE` systemic
  detection and decline-code-based diagnosis work fully without it.
- **Why it matters:** sharpens diagnosis and systemic-detection precision at
  real issuer-level granularity; not needed for the demo — the `hard_stop_mac`
  scenario honestly *simulates* a directive that has already arrived rather
  than performing a live lookup, which is sufficient and clearly documented
  as such.
- **Dependency:** **U-08 must be resolved first** (a maintainer decision, not
  implementation work). Both downstream items share this one blocker and
  should be scoped as **one** milestone once U-08 is answered, not built
  separately.
- **Priority:** 7. **Complexity:** MEDIUM once U-08 is resolved (extraction is
  a context/model addition; the lookup itself reuses the existing
  `MacCodeRegistry.tier_for`).
- **Data model:** **yes** — a new issuer/BIN field somewhere (exact shape is
  what resolving U-08 decides) → **migration required**.
  **State machine:** no. **External services:** no.

**C5. Systemic threshold calibration** (`systemic_baseline_floor_per_min` /
`systemic_absolute_count_floor` — U-04 placeholders).
- **Current state:** invented, untuned defaults; irrelevant at demo scale (the
  demo never injects enough volume to approach them).
- **Dependency:** real or synthetic bulk failure-rate data (doesn't exist yet).
- **Priority:** 8. **Complexity:** LOW (config change once data exists).
  **Data model / state machine / external services:** no / no / no.

**C6. Secrets management** (Vault / SOPS / cloud KMS).
- **Current state:** `.env` + compose `env_file` only (Module 11, by design —
  free-tier, demo-scope).
- **Why it matters:** required before any real credential (Razorpay live keys,
  the C1 channel tokens) is handled.
- **Dependency:** none technically; should land alongside/before C1's
  credentials exist.
- **Priority:** 5 (parallel with C1). **Complexity:** MEDIUM.
  **Data model / state machine:** no / no. **External services:** yes (a
  vault/KMS provider).

**C7. Process manager / autoscaling / multi-host orchestration.**
- **Current state:** `docker-compose`, single host (D-129).
- **Why it matters:** only once real traffic exceeds one host.
- **Dependency:** none blocking; sequence whenever real load exists.
- **Priority:** 9. **Complexity:** HIGH. **Data model / state machine:** no /
  no. **External services:** yes (a hosting platform/orchestrator).

**C8. CI/CD pipeline + Docker image registry publishing.**
- **Current state:** none; build/lint/test contracts covered by the local
  pytest suite only.
- **Dependency:** none. **Priority:** 6. **Complexity:** MEDIUM.
  **Data model / state machine:** no / no. **External services:** yes (a CI
  provider / registry).

**C9. Docker smoke test in CI** (an actual `docker compose --profile full up`,
automated).
- **Current state:** `tests/test_infra_*` assert the compose/Dockerfile
  *contract* without Docker; the real smoke test has been run manually twice
  (Modules 11 and 9b), both green, and is documented in each milestone report.
- **Dependency:** **C8** (needs a CI runner with Docker-in-Docker).
- **Priority:** 6. **Complexity:** MEDIUM. **Data model / state machine:**
  no / no. **External services:** yes (inherits C8's).

**C10. Postgres Row-Level Security.**
- **Current state:** application-layer `TenantScope` only (D-001); every path
  already goes through it, test-enforced — not a known gap, defense-in-depth.
- **Dependency:** none. **Priority:** 8. **Complexity:** MEDIUM.
  **Data model:** yes (RLS policies — a migration). **State machine:** no.
  **External services:** no.

**C11. DPDP erasure-request intake** (UI/endpoint).
- **Current state:** `Counterparty.redact_pii()` exists and is unit-tested;
  nothing lets a merchant or customer *trigger* it.
- **Dependency:** none. **Priority:** 7. **Complexity:** LOW–MEDIUM.
  **Data model / state machine / external services:** no / no / no.

**C12. `Action.content_sent` redaction cascade on erasure.**
- **Current state:** column exists; not cascaded by `redact_pii()`.
- **Dependency:** C11 (needs a trigger to cascade from). **Priority:** 7.
  **Complexity:** LOW. **Data model / state machine / external services:**
  no / no / no.

**C13. Observability** (structured logging / minimal metrics).
- **Current state:** none beyond `/health` + `/health/ready` — deliberately
  minimal (Module 11, D-132: no Prometheus/Grafana/ELK/OTel).
- **Dependency:** none. **Priority:** 9. **Complexity:** MEDIUM.
  **Data model / state machine:** no / no. **External services:** possibly (a
  log/metrics sink, if one is chosen).

**C14. `PlaybookRun.status` runtime transitions**
(`RUNNING → PAUSED/COMPLETED/HALTED_BY_GUARDRAIL/ESCALATED/CANCELLED`).
- **Current state:** the column defaults to `RUNNING`; the *case*-level state
  machine (`RevenueLeakCase.status`) is what the Agent Console and dashboard
  actually read — `PlaybookRun.status` has no consumer today, so this is an
  unfinished column, not a known-broken behaviour.
- **Dependency:** none. **Priority:** 9. **Complexity:** LOW–MEDIUM.
  **Data model:** no (column exists). **State machine:** no — this enum is
  explicitly *not* owned by `state_machine.py` (D-011). **External services:** no.

**C15. `(merchant_id, counterparty_id)` and `(merchant_id, closed_at)`
indexes** on `revenue_leak_case` (deferred at demo scale — D-108, Module 9
note).
- **Current state:** not added; no measured slowness at demo row counts.
- **Dependency:** none. **Priority:** 9. **Complexity:** LOW.
  **Data model:** **yes (index-only migration)**. **State machine / external
  services:** no / no.

### D — FUTURE / OPTIONAL (do not schedule; revisit only on the stated trigger)

- **D1. A real Temporal engine / self-hosted cluster.** **D-090 stands, not
  reopened** (reaffirmed by D-127, Module 11) — a future driver swap behind
  `execute_due_job` only, and only if the Postgres-polling driver proves
  insufficient at a scale the demo/current build never reaches.
- **D2. Learned individual uplift model** (XGBoost + SHAP + T-/X-learner
  meta-learners, Decision F / §8.4). Trigger: 500+ resolved cases — a data
  threshold, not an engineering blocker. The feature set is already named and
  collected (§8.4); no schema change needed when it lands.
- **D3. Card Account Updater (CAU).** No free tier — excluded entirely (Part E
  item 6).
- **D4. SMS production path.** Needs TRAI DLT template registration — an
  external regulatory dependency, not code (Part E item 5).
- **D5. NACH cross-instrument aggregation** (cheque + NACH dishonours). Needs
  bank-side visibility Torque does not have (Part E item 4).
- **D6. Remaining Module 2 residue** — per-decline retry-budget increment
  semantics beyond seed-to-1, real NPCI NACH return-code ingestion,
  `MacCodeRegistry` full seed + unseeded-code self-healing, instrument-key
  HMAC/pepper hardening, a real storefront pixel for Leg 2, counting
  `subscription.charged.failed` in the systemic rollup (D-073) — all low-value
  pre-real-scale, none blocking anything above.
- **D7. WhatsApp `AUTHENTICATION` template category; Meta/WABA template +
  status sync.** No current use case (D-041).
- **D8. Cross-stratum merge widening** (Module 6 residual, D-102). A
  documented, safe fallback (solo send) already exists at demo scale.

### Dependency graph (not a priority ranking — an ordering constraint)

```
A1 (auto-dispatch wiring) ── no dependency ── do this first
  └─ enables real execution to ever fire on live (non-demo, non-test) traffic
       └─ C1 (real channel adapters, needs 4 external accounts)
            └─ C2 (GENERATE_PAYMENT_LINK / LOG_PROMISE execution)
                 └─ C3 (Action.cost population)

B1 (cross-leg / B2B live scenarios) ── independent of A1 ── do alongside A1
B2 (inline-diagnose fallback)       ── superseded by A1; only if A1 skipped
B3 (bigger incrementality cohort)   ── independent, lowest priority in B

U-08 (issuer/BIN extraction — an unresolved DESIGN question, not code)
  ├─→ C4a: §5.3 MAC first-touch lookup (D-083)
  └─→ C4b: ISSUER_SPECIFIC systemic detection
       (C4a and C4b are independent of EACH OTHER once U-08 resolves —
        not sequential; both wait on the same one upstream decision)

C6 (secrets management)  ── should land alongside/before C1's real credentials
C8 (CI/CD + registry) → C9 (Docker smoke test in CI, needs C8's runner)
C11 (DPDP erasure intake) → C12 (content_sent redaction cascade, needs C11)
C5, C7, C10, C13, C14, C15 ── independent of everything above; sequence
  whenever convenient post-demo, in any order

D1–D8 ── independent of all of the above; each waits on its own stated
  trigger (scale, data volume, or an external/regulatory dependency), not on
  any engineering work in this document
```

### Recommended implementation order

1. **This milestone (Module 12)** — documentation only, no code.
2. *(Maintainer's call, optional but recommended)* **"Module 12a — Close the
   Autonomous Loop"** — A1 + B1. Both LOW–MEDIUM complexity, no schema change,
   no state-machine change, no external service, no dependency on anything
   else. Makes Module 13's script beats 2/3/4 fully live instead of partly
   scripted / partly static.
3. **Module 13 — Demo Script.** Works today with or without step 2; strictly
   stronger with it. (Still needs Part D item 4 — a real judging rubric, if one
   exists — per U-05.)
4. **Post-demo, opportunistically, in any order within each branch:**
   C6 + C8 (secrets + CI foundation) → C1 + C2 → C3; independently, C9 once C8
   exists; independently, resolve U-08 → C4; independently, C5 / C7 / C10 /
   C11 → C12 / C13 / C14 / C15.
5. **D-track** — revisit only when its specific trigger condition is met.

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
- ✅ **DONE in Module 12a:** dispatch to Module 3 (D-080) — every ingestion
  case-creating path now dispatches `diagnose_case_task` for the canonical case
  once its own transaction commits (`torque.ingestion.tasks.dispatch_diagnosis`,
  D-137/D-138). **Residual, deliberately not extended:** an ingestion-created
  case still resumed from `SYSTEMIC_HOLD → DIAGNOSING` by the separate §2.5
  systemic-resolution sweep (M7c) is **not** itself re-dispatched by this
  change — that sweep creates no new case and calls no `on_case_ready` hook.
  See `MILESTONES.md` "Module 12a".
- ✅ **DONE in Module 11:** the `docker-compose` `worker` / `beat` services (and
  `api` + one-shot `migrate`) — behind a `full` profile, one reusable
  `Dockerfile`. See `MILESTONES.md` "Module 11 — Tech Stack & Infra".

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
- ✅ **DONE in Module 12a:** the Module 3 → Module 4 auto-dispatch trigger
  (D-088) — `diagnose_case_task` enqueues `activate_case_task` for the same
  case on `ROUTED_TO_PLAYBOOK`, once its own transaction has committed
  (`torque.diagnosis.tasks._dispatch_activation`, D-137). See `MILESTONES.md`
  "Module 12a".

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
- 🔧 **`Action.cost`** population by Module 5 — stays nullable (Module 9 reporting
  concern). *(Module 8's forward cost reads `ChannelRateCard` directly — done.)*
- 🔧 **`MacCodeRegistry` self-healing** (§5.3) — unseeded code → default
  `TIER_2_CAPPED_RETRY` + flagged `CaseEvent` (`tier_for()` still returns `None`).
  Blocked with the first-touch MAC lookup on U-08 / D-083.
- ✅ **DONE in Module 12a:** the Module 4 → Module 5 hand-off (D-093) —
  `torque.policy.tasks.activate_case_task` calls `schedule_run` directly on
  `RUN_CREATED`, in the **same** transaction as `activate_case` (not a further
  Celery hop). See `MILESTONES.md` "Module 12a".

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
- ✅ The real Module 8 `(probability × amount_at_risk) ÷ cost` score — **DONE in
  Module 8**: `torque.coordination.outreach_coordinator.priority(session, case)`
  now returns `torque.scoring.compute_recovery_score(...).score` (D-098 / D-113).
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

## Module 8 — Recovery Scoring Model — ✅ COMPLETE

Built in the Module 8 run (`torque.scoring` package + migration 0017). Now
**DONE**:
- ✅ `cold_start_probability(leg_type, days_since_failure, *, amount_at_risk)` —
  Decision F's exact 8-value table as a live function; bucket boundaries explicit
  and tested. `amount_bucket` retained in the signature, inert (D-110).
- ✅ Warm-start adjustment — `warm_start_multiplier` linear map
  `0.5 + rate·0.8`, clamped `[cap_low, cap_high]` from
  `PolicyConfig.warm_start_cap_low/high` (D-110). `None` history → ×1.0.
- ✅ Cost sourcing — `compute_cost` sums `ChannelRateCard.rate_per_unit` for the
  next playbook step's channel(s) (live run's `active_step_id`, else candidate
  playbook entry); zero/unpriced/absent floors at
  `PolicyConfig.recovery_score_cost_floor` (₹0.01, D-111).
- ✅ `compute_recovery_score` / `RecoveryScore` — the one formula, exact
  `Decimal`, `.explain()` (§8.7) + `.to_dict()` (JSONB). Persisted on
  `revenue_leak_case.recovery_score` / `_breakdown` / `_updated_at` (D-109).
- ✅ Recompute cadence — inline on creation (4 ingestion paths) + diagnosis
  completion; daily Celery-beat sweep (`recompute_open_case_scores_task`,
  `crontab(hour=2, minute=0)`); `recompute_open_cases` also refreshes queued
  cases' `human_queue.priority` (D-112).
- ✅ Module 6 integration — `outreach_coordinator.priority(session, case)` returns
  the real score; `merge` + `human_queue` consume it through that one seam
  (INV-56, D-113).

Still deferred within Module 8's area:
- 🔮 **XGBoost + SHAP + T/X-learner uplift** upgrade (needs 500+ resolved cases —
  Decision F / §8.4). The feature set is named; no schema change needed when it
  lands, only a new consumer.
- 🔧 **Dashboard "top at-risk cases"** view and Module 9 reporting *consume*
  `recovery_score` — their own later modules.
- 🔧 **Agent Console queue re-sort** on score drift between daily sweeps
  (Module 10). The daily sweep refreshes `human_queue.priority`; a live re-sort
  on every score change is not wired.

## Module 9 — Reporting & Measurement — ✅ COMPLETE (descriptive)

Built in the Module 9 run (`torque.reporting` package + `torque.api.reporting`
router; **no migration** — D-114). Now **DONE**:
- ✅ Outcome-based recovery report — revenue at risk (D-115), recovered amount
  (Torque-credited; `SELF_RECOVERED` reported separately — D-116), recovery rate
  (by count **and** by amount — D-117), unresolved / blocked / deferred / escalated
  (D-118), cost efficiency (`Action.cost` is ~0 until Module 5 populates it —
  reported honestly).
- ✅ ₹ recovered **by leg** (§9.1) + **by action type** (§9.5 secondary) + **by
  recovery type / outcome** (§9.2) + **over time** (`date_trunc` on `closed_at`
  UTC, half-open windows — D-119).
- ✅ Operational / exception report (§9.7) — blocked-by-reason (the §9.1 exception
  list), deferred, failed-by-type, escalations-by-reason, terminal-by-status.
- ✅ Batch report over an `opened_at` window (§9.4); case-level drill-down
  (`/cases`, `/cases/{id}`) + the explainability panel (the raw `CaseEvent`
  stream in `event_seq_id` order — §9.2, "the query IS the feature").
- ✅ Read-only, tenant-scoped, derived on demand (INV-58) — 8 `GET` endpoints,
  same FastAPI conventions as Module 2.

Still deferred within Module 9's area:
- ✅ **DONE in Module 9b:** incrementality / causal measurement — treatment-vs-
  control **lift**, the **Wilson score CI** per cohort + **Newcombe (1998)**
  interval for the difference (D-134), and the Blueprint §6 **cross-merchant
  SUTVA-adjusted lift** shown alongside (D-133 / D-135).
  `torque.reporting.incrementality` + `GET /reports/{m}/incrementality` + a
  dashboard card; read-only, tenant-scoped, **no migration** (the
  `in_control_cohort` / `control_group` inputs already existed). See
  `MILESTONES.md` "Module 9b". **U-10 resolved.**
- 🔧 **`Action.cost` population** by Module 5 — until then `total_action_cost` /
  `cost_efficiency_ratio` are ~0 (a data gap, not a Module 9 gap).
- 🔮 **Learned / individual uplift** — XGBoost + SHAP + T/X-learner meta-learners
  for *per-case* incremental effect (Decision F / §8.4, needs 500+ resolved
  cases). Module 9b delivers the *average* treatment effect only; the schema is
  already feature-store-ready.
- 🔧 Pure **timing defers** (quiet hours, UPI peak) write no `Action` row, so
  they are not countable from `Action` — only `OUTREACH_COORDINATOR_DEFERRED` is
  (D-118).
- 🔧 A `(merchant_id, closed_at)` index + a SQL `GROUP BY` rewrite of the summary
  path if a merchant ever exceeds ~10k open cases (D-114 — demo scale does not
  need it).
- 📋 The **merchant dashboard / agent console** UI that consumes these endpoints
  — Module 10.

## Module 10 — UI/UX — ✅ COMPLETE

Built in the Module 10 run (`torque.ui` static SPA + `torque.agent_console` +
`torque.demo`; migration **0018**). Now **DONE**:
- ✅ **Merchant dashboard** — Module 9 metrics (₹ recovered dominant,
  `SELF_RECOVERED` separate, recovery rate, unresolved, escalations,
  blocked/deferred, cost efficiency), recovery-by-leg, recovery-over-time chart,
  top-at-risk ranked list (Module 8 `recovery_score` order, backend), exception
  list surfaced prominently (§10.1–10.3, 10.11).
- ✅ **Case detail / explainability** — the "WHY THIS CASE?" panel rendering
  `recovery_score_breakdown.explain` verbatim + the full `CaseEvent` timeline in
  `event_seq_id` order (§10.5–10.6).
- ✅ **Agent Console** — human queue (priority order) + **pause / unpause /
  resolve** write-backs: `torque.agent_console.resolve_escalation`
  (`ESCALATED_TO_HUMAN → {RECOVERED, PARTIALLY_RECOVERED, WRITTEN_OFF}` +
  `escalation_resolution` + `HUMAN_RESOLVED` + queue removal), the recovery write
  guarded by `guards.human_resolution_writer` (§10.7–10.8, INV-59, D-123).
- ✅ **Demo Surface** — `torque.demo.seed_demo` (deterministic 16-case `acc_demo`
  dataset) + `inject_scenario` (one-click checkout / payment-failure / Decision-K
  hard-stop-MAC / UPI-cap / NACH-ceiling, composing the real ingestion +
  compliance code) + a polling live feed (`/reports/{m}/activity`, 3 s)
  (§10.9–10.10, 10.16–10.17, D-124/125).
- ✅ **Runnable** — `uv run python -m torque` serves API + `/ui` on one port
  (static SPA, no Node, no build — D-122).

Still deferred within Module 10's area:
- 🔧 A **browser / end-to-end test harness** (Playwright/Selenium) — out of the
  stack (D-122); the DOM logic is verified through its API contract + shell/
  wiring assertions.
- 🔧 Real **live push** (WebSocket / SSE) — polling suffices for the demo
  (D-124); the backend has no push channel.
- ✅ **DONE in Module 9b:** the dashboard now surfaces incrementality — a
  compact causal card (treatment/control rate, lift + Wilson CI, SUTVA-adjusted
  lift), rendered from `/reports/{m}/incrementality`, computing nothing in JS.
- 🔧 `escalation_resolution` is a Module-10 vocabulary (`RECOVERED_BY_HUMAN` /
  `PARTIALLY_RECOVERED_BY_HUMAN` / `WRITTEN_OFF`) — the blueprint names the field
  but not its values (U-11).

## Module 11 — Tech Stack & Infra — ✅ COMPLETE

Built in the Module 11 run (`Dockerfile` + `.dockerignore` + rewritten
`docker-compose.yml` + `.env.example`; `torque.api.health`; `Settings.api_host`/
`api_port`). Now **DONE**:
- ✅ The reproducible local/demo runtime — `docker compose --profile full up` →
  `db + redis + migrate + api + worker + beat` from one reusable image
  (D-128/129/130); a bare `docker compose up` still starts only `db` + `redis`
  so the host `uv run python -m torque` loop is untouched.
- ✅ Config coherence — `.env.example` covers the full `Settings` + `PolicyConfig`
  surface (test-enforced parity), no committed secrets, fail-closed defaults;
  `Settings` now owns the API bind address (D-131).
- ✅ Minimal operability — `GET /health/ready` (Postgres `SELECT 1` + Redis
  `PING`), `GET /health` unchanged (D-132).
- ✅ Backend language recorded as **Python** (Part D item 2 / U-05, D-126).

Still deferred / future within Module 11's area:
- 🔮 **Real Temporal engine / self-hosted cluster** — D-090 stands; Temporal is a
  future driver-swap behind `execute_due_job` only, never implemented (D-127).
- 🔮 **Production process manager / autoscaling / multi-host orchestration** —
  compose is the demo/local runtime; no Kubernetes, no Nomad, no ECS.
- 🔮 **Secrets management** (Vault / SOPS / cloud KMS) — `.env` + compose
  `env_file` only.
- 🔧 **CI/CD pipeline** + container-image registry publishing — no owner yet;
  out of the Module 11 scope (build/lint/test contracts are covered by the
  pytest suite).
- 🔧 **Container smoke test in CI** — the infra tests parse the config contract
  without Docker; an actual `docker compose --profile full up` smoke test is a
  manual maintainer step.

## Module 12a — Close the Autonomous Loop — ✅ COMPLETE

Built in the Module 12a run (`torque.ingestion.tasks.dispatch_diagnosis`,
`torque.diagnosis.tasks._dispatch_activation`, `torque.policy.tasks.
activate_case_task`'s inline `schedule_run` call; `torque.demo.scenarios`
`cross_leg_merge` / `b2b_invoice_bundle`). Now **DONE** — see this file's top
"Build Roadmap Priority Classification" section (item A1/B1) and
`MILESTONES.md` "Module 12a" for the full breakdown:
- ✅ **A1** — the ingestion → diagnosis → policy-activation →
  execution-scheduling autonomous chain (resolves D-080/D-088/D-093 — struck
  from the Module 2/3/4/5 lists above).
- ✅ **B1** — live `cross_leg_merge` / `b2b_invoice_bundle` demo scenarios,
  exercising the real §2.4 Merge and §3 B2B grouping rule for the same
  counterparty.

Still deferred / residual within Module 12a's area:
- 🔧 The §2.5 systemic-hold/resume sweep (M7c) does not itself dispatch
  diagnosis for a case it resumes to `DIAGNOSING` — deliberately out of scope
  (a separate, self-contained mechanism; see `ARCHITECTURE.md` §8L's scope
  note). Not blocking anything; the sweep still works exactly as before.
- 🔧 Everything Module 12 classified as Category C/D (real channel adapters,
  the U-08-gated MAC lookup / `ISSUER_SPECIFIC` detection, secrets management,
  CI/CD, etc.) remains exactly as classified — none pulled forward by this run.

## Module 13 — Demo Script

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
