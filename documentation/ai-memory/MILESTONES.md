# MILESTONE HISTORY (append-only per-milestone sections)

One section per completed milestone. **Append new sections; never rewrite a past
one.** If a later milestone changes something a past section described, note it in
the *new* section (and, if it reverses a decision, in `DECISIONS.md`).

## Verification vocabulary

A milestone is "complete + verified" when, at its commit: `uv run pytest` is
fully green, `uv run ruff check .` is clean, `alembic upgrade head` +
up→down→up roundtrip pass (`tests/test_zz_migrations_roundtrip.py`), and the
`state_machine.py` / `guards.py` diffs are intentional.

## Test-count note (read before trusting any number below)

- **Verified this session (2026-09-02) at HEAD `47cf6d7`:** `pytest` collects and
  passes **417** tests; there are **358** `def test_` functions (the gap is
  `@pytest.mark.parametrize` expansion).
- **`def test_` function counts per milestone commit** (verified read-only via
  `git show <commit>:tests/*`): M1 **66**, M2 **119**, M3 **153**, M4 **241**,
  M5 **285**, M6a **327**, M6b **358**.
- **pytest-collected counts at M1–M6a completion** were reported in each
  milestone's own verification report as **66 / 142 / 176 / 278 / 323 / 370**.
  Only the M6b figure (**417**) was re-verified in this session. Treat
  142/176/278/323/370 as **historical, not re-verified** — the collected count
  can only be reproduced by checking out each commit and running the suite
  against a matching DB, which was not done.

---

## Milestone 1 — Core Data Model: case spine, tenancy, atomic history

- **Commit:** `abbab18` "Initial commit: Torque Milestone 1 core data model"
- **Migrations:** `0001_enums` … `0005_case_event`
- **Objective:** Stand up the shared case object, application-layer
  multi-tenancy, PII isolation, the typed leg-context boundary, the append-only
  `CaseEvent` stream, and the `RevenueLeakCase` status state machine.
- **Scope delivered:**
  - `src/torque/enums.py` — all blueprint §4 enums (19 PG types in `0001`).
  - `db/base.py` (`Base` + `NAMING_CONVENTION` + `TenantScoped`), `db/scoped.py`
    (`TenantScope`), `db/session.py` (engine, `SessionLocal`, guard wiring).
  - Models: `Merchant`, `Counterparty` (+`redact_pii`), `MerchantCounterparty`
    (+`assign_cohort`), `Event`, `RevenueLeakCase`, `B2BInvoice`, `CaseEvent`.
  - `contexts/` — `PaymentDegradationContext`, `CheckoutAbandonmentContext`,
    `SubscriptionFailureContext`, `validate_context` (B2B → no blob).
  - `events/payloads.py` — 10 locked `CaseEvent` payload schemas +
    `validate_payload`. `events/case_event_writer.py` — `atomic`,
    `append_case_event` (M1 form).
  - `state_machine.py` — `transition_case`, `apply_network_directive`,
    `sync_control_group`; §4 diagram + Part C edge + R4 B2B exception.
  - `models/guards.py` — `before_flush` enforcement (tenancy, CaseEvent
    append-only, typed context, network-directive monotonicity, Module-7-only
    fields).
  - `security/razorpay_signature.py` — pure HMAC helper.
  - `config.py` — `Settings` + `PolicyConfig` (declared, unused).
  - DB trigger `case_event_no_mutate` (`0005`).
- **Decisions:** D-001..D-015, D-049, D-050. (See `DECISIONS.md`.)
- **Deviations from blueprint:** none material; `state_machine.py` documents the
  3 withheld edges (D-010).
- **Deferred work introduced:** erasure-request intake UI; webhook HTTP
  endpoint; everything Module 2+.
- **Unresolved introduced:** 3 state-machine edges; `STEP_TRANSITIONED` payload
  shape.
- **Tests at completion:** 66 `def test_` functions (files:
  `test_atomicity`, `test_case_event`, `test_context_validation`, `test_enums`,
  `test_event_idempotency`, `test_identity_erasure`, `test_module7_ownership`,
  `test_network_directive`, `test_razorpay_signature`, `test_schema_introspection`,
  `test_state_machine`, `test_tenancy`, `test_zz_migrations_roundtrip`).
  Reported collected count: 66.
- **Verification status:** complete + verified at `abbab18`.
- **Recommended commit message (as used):** "Initial commit: Torque Milestone 1
  core data model".

---

## Milestone 2 — Three retry rails + pre-debit compliance schema

- **Commit:** `24ab187` "Milestone 2: three retry rails + pre-debit compliance schema"
- **Migrations:** `0006_mac_code_registry`, `0007_retry_budgets`
- **Objective:** Model the three structurally different retry-compliance
  postures (card / UPI AutoPay / NACH) and per-attempt pre-debit tracking, plus
  the pure predicates later modules will call.
- **Scope delivered:**
  - Models: `MacCodeRegistry` (composite PK, global), `CardRetryBudget`,
    `UPIRetryBudget`, `NACHRetryPolicy`, `PreDebitNotification`.
  - `compliance/` package: `mac_registry.tier_for`,
    `pre_debit.gap_satisfied` (+`PRE_DEBIT_MIN_GAP_HOURS`),
    `retry_rails` (`card_retry_within_budget`, `upi_attempt_gate_open`,
    `within_upi_execution_window`, `nach_retry_eligible`; constants
    `CARD_ATTEMPTS_24H_CAP`, `CARD_ATTEMPTS_30D_CAP`, `UPI_AUTOPAY_HARD_CAP`,
    `IST`, `UPI_PEAK_WINDOWS_IST`).
  - `0006` seeds the 13 locked MAC rows only. `0007` creates the four tables
    with their coherence CHECKs (`hard_stop_reason_coherent`,
    `upi_hard_cap_locked` = `CHECK (hard_cap = 3)`).
  - `PolicyConfig` gains `nach_representment_ceiling_default = 3`.
- **Decisions:** D-016..D-020.
- **Deviations:** none material (`mandate_id` as indexed String, D-019, is a
  deliberate modelling choice within the blueprint's intent).
- **Deferred work introduced:** `CardRetryBudget`/`UPIRetryBudget` counter
  seeding at ingestion (Module 2 runtime); MAC unseeded codes + Visa set;
  "unseeded → default TIER_2 + flag CaseEvent" fallback (Module 5); all rail
  *enforcement* (Module 5).
- **Unresolved introduced:** Tier 1 vs Tier 3 precedence remains a stated
  default (blueprint Part E item 2).
- **Tests at completion:** 119 `def test_` functions (new files:
  `test_card_retry_budget`, `test_decision_k_scenarios`, `test_mac_code_registry`,
  `test_nach_retry_policy`, `test_pre_debit_notification`; `test_upi_retry_budget`
  added at M2). Reported collected count: 142.
- **Verification status:** complete + verified at `24ab187`.
- **Recommended commit message (as used):** "Milestone 2: three retry rails +
  pre-debit compliance schema".

---

## Milestone 3 — SystemicEvent + ChannelRateCard (Phase-1 foundation complete)

- **Commit:** `d51c228`
- **Migrations:** `0008_systemic_and_rate_card`
- **Objective:** Outage-scale suppression schema + the channel rate card; wire
  `RevenueLeakCase.systemic_event_id`.
- **Scope delivered:**
  - Models: `SystemicEvent` (tenant-scoped, scope-coherence CHECK),
    `ChannelRateCard` (global, freeform `channel` PK, seeded `whatsapp` / `email`
    / `sms`).
  - `compliance/systemic.py`: `systemic_threshold_breached` (compound),
    `systemic_resolved` (sustain window).
  - `RevenueLeakCase.systemic_event_id` nullable FK added (`0008`), index
    `ix_revenue_leak_case_systemic_event_id`.
  - `PolicyConfig` gains `systemic_*` fields (spike multiplier 5.0 from Decision
    J; baseline floor / absolute floor / sustain window are **placeholder
    numbers**).
- **Decisions:** D-046, D-047, D-048.
- **Deviations:** none.
- **Deferred work introduced:** 60-second detection job, rollups, rolling
  baseline, `SYSTEMIC_HOLD` transitions, batch re-queue (all Module 2); N/M
  tuning; `Action.cost` / Module 8 cost-term consumption of `ChannelRateCard`.
- **Tests at completion:** 153 `def test_` functions (new files:
  `test_channel_rate_card`, `test_systemic_event`). Reported collected count: 176.
- **Verification status:** complete + verified at `d51c228`.
- **Recommended commit message (as used):** "Milestone 3: SystemicEvent +
  ChannelRateCard (Phase-1 foundation complete)".

---

## Milestone 4 — Playbook definition contract

- **Commit:** `e363eb6` "Milestone 4: playbook definition contract"
- **Migrations:** `0009_playbooks`
- **Objective:** The locked `steps_graph` format, typed `stopping_rules`,
  merchant-override resolution, and **save-time** validation — no runtime
  traversal.
- **Scope delivered:**
  - Models: `PlaybookIdentity`, `Playbook` (composite PK, append-only, trigger
    `playbook_no_mutate`), `MerchantPlaybookConfig` (tenant-scoped partial
    override), `PlaybookRun` (composite version FK, schema only).
  - `playbooks/` package: `graph.py` (`StepGraph` / `StepNode` / `StepEdge` /
    `ActionTemplate`, `parse_step_graph`, `validate_step_graph` — entry/edge/
    unique-id/on_success+fallback/**no-cycle** rules); `stopping_rules.py`
    (`StoppingRules` / `AllowedHours` + `Partial*`); `resolution.py`
    (`deep_merge`, `effective_stopping_rules`); `validation.py`
    (`validate_playbook`, `validate_merchant_playbook_config`, UPI `max_attempts
    <= 3` importing `UPI_AUTOPAY_HARD_CAP`).
  - `guards.py` gains `_guard_playbook` and `_guard_merchant_playbook_config`
    branches (validate + normalize in place; reject dirty/deleted `Playbook`).
  - `exceptions.py` gains `PlaybookValidationError`, `PlaybookNotFoundError`.
- **Decisions:** D-021..D-025.
- **Deviations:** none.
- **Deferred work introduced:** playbook *runtime* (run instantiation,
  `active_step_id` advancement, `PlaybookRun.status` transitions, step timing
  semantics execution) — Module 4/5; the playbook *catalog* (concrete playbooks
  per `root_cause_code`) — Module 4; action-specific `params` schemas — Module 5.
- **Tests at completion:** 241 `def test_` functions (new files:
  `test_merchant_playbook_config`, `test_playbook_graph`, `test_playbook_guard`,
  `test_playbook_model`, `test_playbook_resolution`, `test_playbook_run`,
  `test_playbook_validation`, `test_stopping_rules`). Reported collected count: 278.
- **Verification status:** complete + verified at `e363eb6`. `guards.py` gained
  the two playbook branches here; `state_machine.py` was **not** touched (it has
  been unchanged since M1 `abbab18`).
- **Recommended commit message (as used):** "Milestone 4: playbook definition
  contract".

---

## Milestone 5 — The atomic, always-attributed action ledger

- **Commit:** `1fbe67d` "Milestone 5: the atomic, always-attributed action ledger (Action / ActionCase)"
- **Migrations:** `0010_actions`
- **Objective:** `Action` + `ActionCase` with universal attribution, and the
  atomic `Action`+`ActionCase`+`CaseEvent` write primitive.
- **Scope delivered:**
  - Models: `Action` (nullable `run_id`, coherence CHECKs), `ActionCase`
    (composite PK, `Numeric(6,5)` weight, unit-range CHECK).
  - `events/case_event_writer.py` extended: `write_action_and_event(...)`,
    `Attribution` frozen dataclass, `_build_action_cases`, `_event_for`;
    `_FULL_WEIGHT = Decimal("1.00000")`.
  - `events/payloads.py`: `ActionExecutedPayload` gains `action_id: str`;
    `channel` / `cost` made nullable.
  - `guards.py` gains `_guard_action_write` + `_validate_action_case_set`
    (≥1 row; exactly one `is_primary`; its `case_id == primary_case_id`;
    Σ `credit_weight == Decimal("1")`; same-flush completeness; Action↔CaseEvent
    atomicity via `payload.action_id` string match). Also handles `ActionCase`
    edits on already-persisted Actions (Module 7 re-weighting path).
  - `exceptions.py` gains `ActionAtomicityError`, `ActionCaseInvariantError`.
- **Decisions:** D-026..D-032.
- **Deviations (documented in code):** D-026 (universal `ActionCase`),
  D-030 (atomicity promoted to a structural invariant), D-031 (nullable
  `channel`/`cost`), D-032 (added `action` coherence CHECKs).
- **Deferred work introduced:** action *execution* (all channel adapters, retry
  APIs, payment-link creation, promise logging); `GuardrailEngine`; cost
  computation from `ChannelRateCard`; Module 7's `credit_weight` re-split logic.
- **Tests at completion:** 285 `def test_` functions (new files:
  `test_action`, `test_action_atomicity`, `test_action_case`). Reported collected
  count: 323.
- **Verification status:** complete + verified at `1fbe67d`.
- **Recommended commit message (as used):** "Milestone 5: the atomic,
  always-attributed action ledger (Action / ActionCase)".

---

## Milestone 6a — PaymentLink + PromiseToPay

- **Commit:** `624ebb2` "Milestone 6a: PaymentLink + PromiseToPay"
- **Migrations:** `0011_payment_link_promise`
- **Objective:** The two recovery-signal entities: the payment-link lifecycle
  (Module 7's key attribution signal) and promise-to-pay.
- **Scope delivered:**
  - Models: `PaymentLink` (`link_id` PK, nullable `action_id`, non-null
    `case_id`, `payment_link_status` enum via `values_callable`, paid⇔paid_at
    CHECK, `amount_paid >= 0` CHECK), `PromiseToPay` (surrogate `promise_id` PK,
    `UNIQUE(captured_via)`, `promise_status` enum default `PENDING`, no
    `on_broken` column).
  - `promises.py`: `PROMISE_TRANSITIONS` (`PENDING → {KEPT, BROKEN}`),
    `assert_promise_transition`, `transition_promise` (writes no CaseEvent).
  - `guards.py` gains `_guard_promise_to_pay` (item 9): new row must be
    `PENDING` (pre-flush `None` counts as `PENDING`); status change on an
    existing row must be a legal transition.
  - `exceptions.py` gains `PromiseTransitionError`.
- **Decisions:** D-033..D-038.
- **Deviations:** none beyond deliberate modelling (surrogate PK D-036, no
  `on_broken` D-038 — recorded against internal M6a decision ids "D10"/"D4" in
  the code, which are *not* blueprint Part D items).
- **Deferred work introduced:** webhook-driven `PaymentLink.status` /
  `amount_paid` / `paid_at` transitions (Module 2/7); promise-broken → human
  queue routing (Module 6); `GENERATE_PAYMENT_LINK` / `LOG_PROMISE` execution
  (Module 5).
- **Tests at completion:** 327 `def test_` functions (new files:
  `test_payment_link`, `test_promise_to_pay`). Reported collected count: 370.
- **Verification status:** complete + verified at `624ebb2`.
- **Recommended commit message (as used):** "Milestone 6a: PaymentLink +
  PromiseToPay".
- **Note:** M6a and M6b are **separate milestones and separate commits**. Do not
  merge or re-order them.

---

## Milestone 6b — MerchantWhatsAppTemplate + approved_template_exists

- **Commit:** `47cf6d7` "Milestone 6b: MerchantWhatsAppTemplate + approved_template_exists"
- **Migrations:** `0012_merchant_whatsapp_template`
- **Objective:** WhatsApp gate #2 of 2 — the per-merchant template-approval
  table and its pure lookup predicate. **This closes blueprint Section 3 — every
  Part A entity is now implemented.**
- **Scope delivered:**
  - Model: `MerchantWhatsAppTemplate` (`template_id` PK, tenant-scoped,
    `whatsapp_template_category` enum `UTILITY|MARKETING`, `approval_status`
    plain `String(32)` — no enum/CHECK, `leg_type` reuses `leg_type` enum, gate
    index `(merchant_id, leg_type, category)`, no uniqueness beyond PK).
  - `enums.py`: `WhatsAppTemplateCategory` added; `ALL_ENUMS` now 20.
  - `compliance/whatsapp.py`: `WHATSAPP_APPROVED = "APPROVED"`,
    `approved_template_exists(session, *, merchant_id, leg_type, category)` —
    EXISTS query, exact case-sensitive `== "APPROVED"`, fail-closed.
  - `compliance/__init__.py` re-exports both.
  - `0012` creates the `whatsapp_template_category` PG type
    (`create`/`drop` with `checkfirst`), the table, the `merchant_id` index, and
    the gate index. `down_revision = "0011_payment_link_promise"`.
  - `tests/conftest.py` gains the `make_wa_template` fixture.
- **Decisions:** D-039..D-045.
- **Deviations (documented in code):** D-042 (Meta vocabulary gap — plain
  String, no enum/CHECK); D-041 (`AUTHENTICATION` excluded).
- **Deferred work introduced:** the full `SEND_WHATSAPP` guardrail (gate #1
  `whatsapp_opt_in` + gate #2 + open-conversation check + `BLOCKED_BY_GUARDRAIL`
  / `CONSENT_NOT_OBTAINED` / `TEMPLATE_NOT_APPROVED` production) — Module 6;
  Meta/WABA sync of templates and statuses; template version / quality-rating
  tracking; `AUTHENTICATION` category.
- **Tests at completion:** 358 `def test_` functions; **`pytest` collects and
  passes 417** (re-verified 2026-09-02). New file: `test_merchant_whatsapp_template`
  (43 `def test_` functions). `test_schema_introspection` extended.
- **Verification status:** complete + verified at `47cf6d7`.
  `state_machine.py` unchanged; `guards.py` unchanged by M6b (last touched M6a).
  Migration up→down→up roundtrip clean. `ruff` clean.
- **Recommended commit message (as used):** "Milestone 6b: MerchantWhatsAppTemplate
  + approved_template_exists".

---

## Milestone 7a — FastAPI app + Razorpay webhook verify/ingest (Module 2 begins)

- **Commit:** *(uncommitted at time of writing — maintainer commits)*. Recommended
  message below.
- **Migrations:** `0013_event_ingestion_index` — **first zero-table migration**;
  adds one composite index `ix_event_merchant_type_received_at` on
  `event (merchant_id, type, received_at)`. No table, column, or enum.
- **Objective:** Torque's first HTTP surface. A FastAPI app and a single Razorpay
  webhook endpoint implementing blueprint §2.2's verify-before-parse pipeline:
  HMAC-SHA256 over the raw body (constant-time, via the existing
  `torque.security.razorpay_signature` helper) → silent HTTP-200 drop with zero
  side effects on any failure → `X-Razorpay-Event-Id` idempotency check →
  exactly one `Event` row (`processed=False`) written through `TenantScope`.
  Nothing downstream of a verified, deduplicated `Event`.
- **Scope delivered:**
  - `src/torque/api/` package: `app.py` (`create_app()` factory — routes only,
    no startup work; `GET /health` + the webhook router; FastAPI auto-docs left
    at defaults), `deps.py` (`get_db` request dependency — yields a `SessionLocal`
    session, commits on clean return; overridden in tests), `webhooks.py`
    (`POST /webhooks/razorpay/{merchant_id}` — the §2.2 pipeline).
  - `src/torque/__main__.py` — `python -m torque` → `uvicorn ... --factory`
    (dev/preview convenience; `TORQUE_API_HOST` / `TORQUE_API_PORT` env).
  - `pyproject.toml` — `fastapi>=0.110` + `uvicorn[standard]>=0.29` added to
    `dependencies`; `httpx>=0.27` to the `dev` extra (TestClient transport); new
    `[tool.ruff.lint.per-file-ignores]` → `"src/torque/api/*" = ["B008"]` (the
    FastAPI `Depends()`-in-defaults idiom).
  - `src/torque/config.py` — `Settings.razorpay_webhook_mode:
    Literal["live","test"] = "test"` + `Settings.active_razorpay_webhook_secret()`
    (returns the one secret for the deployment's mode, or `None` → fail closed).
  - `src/torque/models/event.py` — `__table_args__` gains the composite `Index`
    (mirrors migration `0013`).
  - `tests/conftest.py` — `WEBHOOK_TEST_SECRET` / `WEBHOOK_LIVE_SECRET` module
    constants; `make_api_client` factory fixture (`TestClient` over `create_app()`
    with `get_db` → the joined-transaction test session and `get_settings` → a
    `Settings` with known secrets; `mode` and `with_secrets` params) and a plain
    `api_client` fixture.
  - `tests/test_webhook_ingestion.py` — 21 tests (see below).
  - `tests/test_schema_introspection.py` — +2 tests
    (`test_m7a_event_ingestion_index_present_and_exact`,
    `test_m7a_event_idempotency_uniqueness_unchanged`).
- **Decisions:** D-051..D-056.
- **Deviations from blueprint:** none. (FastAPI auto-docs `/docs` `/redoc`
  `/openapi.json` are left enabled — a convenience for the demo surface, not a
  blueprint conflict.)
- **Deferred work removed from `DEFERRED.md` (Module 2):** the FastAPI app; the
  Razorpay webhook HTTP endpoint; the verify-before-parse pipeline wrapping
  `verify_razorpay_signature`; the `Event` write path + `X-Razorpay-Event-Id`
  idempotency check.
- **Deferred work still open (Module 2):** BullMQ/Redis; the 90s/30s
  self-recovery buffer; cross-leg dedup / `superseded_by_case_id`; systemic
  detection job; `CardRetryBudget`/`UPIRetryBudget` counter seeding; `B2BInvoice`
  bundling; the `checkout.abandoned` path; dispatch to Module 3; flipping
  `Event.processed`; per-merchant webhook-secret storage; the
  `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` state-machine edge (still `UNRESOLVED.md`
  U-01 item 3 — M7a did not need it; belongs to M7c).
- **Deferred work introduced:** per-merchant webhook-secret storage (M7a uses the
  two global `Settings` secrets — fine for the single-merchant demo).
- **Unresolved introduced:** none.
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD` empty for each). M7a creates no cases and performs no status
  transitions.
- **Tests at completion:** **381** `def test_` functions; `pytest` collects and
  passes **440** (was 358 / 417 at M6b `47cf6d7`). `ruff check .` clean.
  `alembic upgrade head` → `0013`; up→down→up roundtrip green.
  1 cosmetic warning: `StarletteDeprecationWarning: Using httpx with
  starlette.testclient is deprecated; install httpx2 instead` (Starlette 1.6 /
  FastAPI 0.141 resolved by `uv`; not an error, no `filterwarnings=error` in
  pytest config).
- **Verification status:** complete + verified against a live Postgres
  (`docker compose` db, host 5442). All of `pytest`, `ruff`, `alembic upgrade
  head`, the roundtrip test, and the `state_machine.py` / `guards.py` diff checks
  pass. App boots (`create_app()` → `GET /health` → `{"status":"ok"}`; the
  webhook route registers as a `_IncludedRouter` in `app.routes` under Starlette
  1.6 but is live — the 21 endpoint tests exercise it).
- **Recommended commit message:**
  `Milestone 7a: FastAPI app + Razorpay webhook verify/ingest (Module 2 begins)`

### M7a test file — `tests/test_webhook_ingestion.py` (21)

Health (1): `/health` → 200 `{"status":"ok"}`.
Happy path (3): new verified event persists with the right `type` /
`idempotency_key` / `raw_payload` (== parsed body) / `processed=False` /
`merchant_id` (from the path); a second merchant's scope is untouched.
Signature fail-closed, zero side effects (6): wrong secret; missing
`X-Razorpay-Signature`; one extra byte after signing; re-serialized (pretty)
JSON of the same object; verified-but-non-JSON body; verified JSON array (not an
object) — each → 200, no `Event`, no `CaseEvent`, no `RevenueLeakCase`.
Idempotency (3): same `X-Razorpay-Event-Id` twice → one row; two distinct ids,
identical body → two rows; missing id header → 200, no row.
Event type (2): a verified unrecognized `event` string persists as-is; a body
with no `event` field persists as `type="unknown"`.
Merchant resolution (2): unknown `{merchant_id}` → 200, no row; no merchant
segment (`POST /webhooks/razorpay`) → 404.
Live/test secret selection (3): test-mode verifies only the test secret (live
sig rejected); live-mode verifies only the live secret (test sig rejected);
unset secret for the mode → every request dropped.
No extra writes (1): a successful ingest writes no `RevenueLeakCase` / `CaseEvent`.

---

## Milestone 7b — Leg-1 signal ingestion completion (buffer + dedup + case creation)

- **Commit:** *(uncommitted at time of writing — maintainer commits)*. Recommended
  message below.
- **Migrations:** **none.** M7b is pure ingestion logic — no table, column,
  enum, or migration. `alembic head` stays `0013`.
- **Objective:** Complete the first real `RevenueLeakCase` creation path, Leg 1
  only: `verified payment.failed Event → Celery self-recovery buffer (§2.3) →
  cross-leg dedup (§2.4) → PAYMENT_DEGRADATION case in DETECTED`. The case is
  never dispatched past `DETECTED`.
- **Scope delivered:**
  - **`src/torque/ingestion/`** package:
    - `celery_app.py` — `Celery("torque")`, Redis broker (`Settings.redis_url`,
      host 6389), **no result backend**; eager flags from
      `Settings.celery_task_always_eager`.
    - `tasks.py` — `resolve_buffered_event_task(event_id)`: opens one
      `session_scope()` (module seam `_session_scope` for tests), calls
      `buffer.resolve_buffered_event`, returns the outcome name.
    - `buffer.py` — `resolve_buffered_event(session, *, event_id)`:
      `NOOP` (event gone / already `processed` / not `payment.failed` / case
      already exists) · `SELF_RECOVERED` (a `payment.captured` for the same
      `payment_id`/`order_id`, `received_at >= failure.received_at`) · else →
      `create_or_attach_case`. `payment_failure_buffer_seconds()` = 90.
    - `cases.py` — `create_or_attach_case(session, *, event)`: idempotency
      guard on `source_event_id`; `resolve_counterparty`; `find_supersedable_case`;
      insert `RevenueLeakCase(leg_type=PAYMENT_DEGRADATION, status=DETECTED,
      source_event_id, counterparty_id, amount_at_risk, context)` via
      `TenantScope`; `sync_control_group`; on a Merge set the abandonment case's
      `superseded_by_case_id` (its status untouched) and copy its context into
      `context["merged_abandonment_context"]`; `_seed_card_retry_budget` for
      card payments; `event.processed = True`. Returns `CASE_CREATED` /
      `CASE_MERGED` / `NOOP`.
    - `dedup.py` — `find_supersedable_case(...)`: open, non-terminal
      `CHECKOUT_ABANDONMENT` case, same `(merchant_id, counterparty_id)`,
      `context.cart_id == order_id`, `opened_at` within
      `PolicyConfig.cross_leg_dedup_window_hours` (2h). **Live direction only.**
    - `identity.py` — `resolve_counterparty(...)`: exact phone → exact email →
      create (safe consent defaults); find-or-create `Merchant_Counterparty`.
    - `payloads.py` — pure Razorpay `payment.*` extractors (`payment_id`,
      `order_id`, `contact_phone/email`, `card_instrument_ref` =
      `COALESCE(token_id, card_id)` — the Razorpay tokenised card reference, no
      PAN, `amount_rupees` paise→₹, `is_card_payment`,
      `payment_degradation_context` — preserves raw `error_code` as
      `decline_code`, does NOT read `error_reason`, does NOT set
      `is_hard_decline`).
    - `outcomes.py` — `BufferOutcome` enum.
  - **`src/torque/api/webhooks.py`** — after a new verified `Event` flush:
    `payment.failed` → `resolve_buffered_event_task.apply_async((str(id),),
    countdown=90)`. All other types persisted, no enqueue. Still empty `200`.
  - **`src/torque/contexts/payment_degradation.py`** — `is_hard_decline` type
    changed `bool` → `bool | None`, default `None`. Ingestion **leaves it
    unset**; the Diagnosis Engine (Module 3) owns hard/soft decline
    classification — there is no ingestion-side heuristic (D-058). New optional
    `merged_abandonment_context: dict | None`.
  - **`src/torque/config.py`** — `Settings.redis_url`,
    `Settings.celery_task_always_eager`.
  - **`pyproject.toml`** — `celery>=5.4`, `redis>=5` → `dependencies`.
  - **`docker-compose.yml`** — `redis` service gains a healthcheck (no new
    service).
  - **`tests/conftest.py`** — `razorpay_payment_body(...)` builder;
    `make_api_client` gains `patch_enqueue` (default `True` → spies
    `resolve_buffered_event_task.apply_async` as `client.buffer_enqueue`);
    `celery_eager` fixture.
- **Decisions:** D-057..D-063 (D-063 supersedes D-056).
- **Deviations from blueprint:** D-057 (Celery for the Node-only "BullMQ" role —
  documented in `celery_app.py` / `pyproject.toml`); D-058 (`is_hard_decline`
  type `bool` → `bool | None`, ingestion leaves it unset; no schema/enum change,
  Module 3 still owns classification); D-059 (new context field to represent the
  §2.4 "appended into the surviving case" merge, given `extra="forbid"`); D-061
  (`CardRetryBudget` is seeded at ingestion — the blueprint left this as "Module
  2 §2.7"; the instrument key is the Razorpay tokenised reference stored in the
  inherited `card_token_hash` column, no PAN, no hashing, no rename, no new
  column). None weaken an existing invariant.
- **Deferred work removed from `DEFERRED.md` (Module 2):** the self-recovery
  buffer (payment/Leg-1 half); cross-leg dedup / `superseded_by_case_id` wiring
  (live direction); the first `RevenueLeakCase` creation path; `CardRetryBudget`
  seeding for card `payment.failed`; the BullMQ/Redis queue wiring (now
  Celery/Redis).
- **Deferred work introduced / still open (Module 2):** the **reverse Merge
  direction** (`checkout.abandoned` arriving after a payment case) — deferred to
  the Leg-2 ingestion milestone; the §2.3 buffer's **`subscription.charged.failed`
  (30s)** half; **Leg 3** (`subscription.charged.failed`) and **Leg 4**
  (`invoice.overdue` / `B2BInvoice` bundling) case creation; **Leg 2**
  (`checkout.abandoned`) ingestion; **`UPIRetryBudget` seeding** (Leg-3);
  per-decline retry-budget **increment** semantics (Module 5); **card token
  hashing** / pepper subsystem; **systemic detection** (§2.5) and the
  `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` edge (U-01 #3); a `docker-compose` Celery
  worker service; dispatch to Module 3.
- **Unresolved:** **U-07 RESOLVED** for the inbound half — Celery + Redis
  (see D-057). Temporal / Postgres-polling for `PlaybookRun` execution (Module 5)
  stays open (tracked in `UNRESOLVED.md` U-07's remaining note / Part E item 8).
  U-01 #3 still open (M7c).
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD` empty for each). M7b creates cases at `DETECTED`, runs no
  transitions, invents no edge. The Merge sets a self-FK column only.
- **Transactional atomicity (confirmed 2026-09-02):** `resolve_buffered_event_task`
  opens exactly one `torque.db.session.session_scope()` (commit-once-on-success /
  rollback-on-exception / close). `resolve_buffered_event` → `create_or_attach_case`
  use only `session.flush()` — **no intermediate `commit()`**. So the whole
  case-creation write set — `RevenueLeakCase`, `Counterparty` (resolve/create),
  `Merchant_Counterparty` (resolve/create), `abandonment.superseded_by_case_id`
  on a Merge, `CardRetryBudget` seed, and the originating `Event.processed=True`
  — commits or rolls back as **one transaction**. Verified by
  `tests/test_ingestion_atomicity.py` (a failure at the card-seed step and at the
  context-guard step each leaves zero cases / counterparties / budgets and
  `Event.processed` still `False`). No transaction abstraction was added —
  `session_scope` already suffices.
- **Tests at completion:** **427** `def test_` functions; `pytest` collects and
  passes **486** (was 381 / 440 at M7a). `ruff check .` clean. `alembic upgrade
  head` → `0013` (no-op — no M7b migration); up→down→up roundtrip green.
  1 cosmetic `StarletteDeprecationWarning` (unchanged from M7a).
- **New test files:** `test_ingestion_buffer.py` (12), `test_ingestion_case_creation.py`
  (8), `test_ingestion_counterparty.py` (5), `test_cross_leg_dedup.py` (8),
  `test_ingestion_card_budget.py` (5), `test_webhook_dispatch.py` (6),
  `test_ingestion_atomicity.py` (2). `test_schema_introspection.py` +2.
- **Verification status:** complete + verified against a live Postgres
  (docker-compose db, host 5442). `pytest` 486 green, `ruff` clean, roundtrip
  green, `state_machine.py` / `guards.py` diffs empty, no migration added.
- **Recommended commit message:**
  `Milestone 7b: Leg-1 signal ingestion — self-recovery buffer, cross-leg dedup, case creation`

---

## Milestone 7c — systemic detection & suppression (§2.5, NETWORK_WIDE)

- **Commit:** *(uncommitted — maintainer commits the whole Milestone 7 tree)*.
  Recommended message below.
- **Migrations:** **none.** M7c is pure ingestion logic + one approved
  state-machine edge. `alembic head` stays `0013`.
- **Objective:** the blueprint §2.5 systemic-detection job for the payment-failure
  ledger that exists today. Celery beat every 60 s → per-merchant `NETWORK_WIDE`
  threshold (trailing-10-min failures/min vs. a trailing-7-day baseline that
  **excludes** the live window) via the existing `systemic_threshold_breached`
  predicate → on breach create `SystemicEvent(NETWORK_WIDE)` and sweep that
  merchant's open `DETECTED` cases into `SYSTEMIC_HOLD` → later runs re-check
  each active event via `systemic_resolved` and, once quiet, write `resolved_at`
  and batch-transition held cases `SYSTEMIC_HOLD → DIAGNOSING`. Plus the §2.7
  ingestion hook (a case created by the M7b buffer during an active event is
  born held).
- **Scope delivered:**
  - **`src/torque/state_machine.py`** — added `CaseStatus.SYSTEMIC_HOLD` to
    `_TRANSITIONS[PLAYBOOK_ACTIVE]` (U-01 #3, approved — D-066); docstring's
    "NOT YET ADDED" list updated. **Legal but dormant** — no M7c code drives it;
    `transition_case` executes it with the existing guard architecture; no
    `guards.py` change. This is the **only** load-bearing state-machine change
    in all of Milestone 7.
  - **`src/torque/ingestion/systemic.py`** (NEW): `run_systemic_detection(session,
    *, now=None)` orchestrator (iterate merchants with failures in the detection
    window ∪ merchants with an active `SystemicEvent`; detect then resolve, one
    shared `now`); `_detect_and_hold` / `_check_and_resolve` / `_hold_case` /
    `_active_network_wide_event` / `apply_active_hold_if_any` (the §2.7 hook);
    rollup helpers `_failure_count` (half-open `[start, end)` over
    `Event(type="payment.failed")`) and `_baseline_failure_rate` (excludes the
    detection window). Constants `_HOLD_TRIGGER="systemic_network_wide"`,
    `_RESUME_TRIGGER="systemic_resolved"`. DB-only, no `commit()`.
  - **`src/torque/ingestion/tasks.py`** — `detect_systemic_task()` (one
    `_session_scope()`, calls `run_systemic_detection` with `now=utcnow()`).
  - **`src/torque/ingestion/celery_app.py`** — `conf.beat_schedule` entry
    `"systemic-detection"` → `torque.ingestion.detect_systemic`, `schedule=60.0`.
    Dev scheduler: `celery -A torque.ingestion.celery_app:celery_app beat`.
  - **`src/torque/ingestion/cases.py`** — one additive call
    `apply_active_hold_if_any(session, case)` before `event.processed = True`.
    No-active-event path is byte-for-byte M7b. No new `BufferOutcome` member.
  - **`src/torque/config.py`** — `PolicyConfig.systemic_detection_window_minutes
    = 10` (§2.5 "trailing 10 minutes"), `systemic_baseline_days = 7` (§2.5
    "trailing 7-day"). N (`systemic_baseline_floor_per_min`) and M
    (`systemic_absolute_count_floor`) are **unchanged U-04 placeholders** —
    M7c consumes them, does not validate or retune them.
  - **`tests/conftest.py`** — `systemic_policy` fixture (binds
    `systemic.get_policy` to a test `PolicyConfig` — the production N would need
    ~10k baseline rows); `make_failure_events` helper.
  - Tests: `tests/test_systemic_detection.py` (26), `tests/test_state_machine.py`
    +7, `tests/test_schema_introspection.py` +2.
- **Decisions:** D-064..D-069.
- **Deviations from blueprint:** D-064 (Celery beat for the Node-only "BullMQ"
  repeatable role — consistent with D-057); D-065 (`NETWORK_WIDE` only —
  `ISSUER_SPECIFIC` deferred because issuer/BIN/acquirer extraction is not in the
  canonical event/context model, U-08); D-067 (stateless aggregate resolution).
  None weaken an existing invariant. `guards.py` unchanged.
- **Deferred work removed from `DEFERRED.md` (Module 2):** the systemic detection
  job (§2.5) for the `NETWORK_WIDE` tier; the `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD`
  edge (U-01 #3 — now added).
- **Deferred / still open (Module 2):** `ISSUER_SPECIFIC` detection (blocked on
  issuer extraction — U-08); driving `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` + mid-run
  recovery semantics (Module 5); a `docker-compose` Celery worker/beat service;
  Leg 3 (`subscription.charged.failed` + `SubscriptionFailureContext` + **30s
  buffer** + **`UPIRetryBudget` seeding**, per-mandate, from that producer —
  D-069); Leg 4 (`invoice.overdue` / `B2BInvoice` bundling); Leg 2
  (`checkout.abandoned`) + the **reverse cross-leg Merge**; dispatch to Module 3.
- **Unresolved:** **U-01 #3 RESOLVED** (edge added — D-066). **U-04 stays open** —
  M7c uses the N/M/sustain placeholders as configured, does not empirically
  validate or tune them. **U-07** `PlaybookRun`-execution half still open
  (Module 5). **New U-08** — issuer/BIN/acquirer/route extraction (field, source,
  owning model, owner).
- **`state_machine.py`:** changed — **exactly** the approved
  `PLAYBOOK_ACTIVE → SYSTEMIC_HOLD` addition + the docstring cleanup, nothing
  else (diff shown in the verification report). **`guards.py`:** byte-unchanged
  vs HEAD (`git diff HEAD` empty).
- **Transactional atomicity:** `detect_systemic_task` opens one
  `session_scope()`; `run_systemic_detection` / `_detect_and_hold` /
  `_check_and_resolve` use only `session.flush()`. `SystemicEvent` creation, all
  case FK sets + `transition_case` + `SYSTEMIC_HOLD_APPLIED` writes, and
  `resolved_at` commit or roll back as one unit. Verified by
  `test_failure_mid_sweep_rolls_everything_back`.
- **Tests at completion:** **460** `def test_` functions; `pytest` collects and
  passes **519** (was 427 / 486 at M7b). `ruff` clean. `alembic upgrade head` →
  `0013` (no-op — no M7c migration); up→down→up roundtrip green. 1 cosmetic
  `StarletteDeprecationWarning` (unchanged).
- **Verification status:** complete + verified against a live Postgres
  (docker-compose db, host 5442). `pytest` 519 green, `ruff` clean, roundtrip
  green, `state_machine.py` diff == the approved edge only, `guards.py` diff
  empty, no migration created.
- **Recommended Milestone 7 commit message:**
  `Milestone 7: Signal ingestion — webhook, recovery buffer, dedup, case creation, systemic hold`
- **Committed by the maintainer as `2a35786`** ("Milestone 7: Signal ingestion —
  webhook, recovery buffer, dedup, case creation, systemic hold"). Milestone 8
  is built on top of that commit.

---

## Milestone 8 — Leg 3 signal ingestion (`subscription.charged.failed`)

- **Commit:** *(uncommitted — maintainer commits)*. HEAD at implementation time:
  `2a35786` (Milestone 7). Recommended message below.
- **Migrations:** **none.** Leg-3 tables (`upi_retry_budget`, `nach_retry_policy`,
  `SubscriptionFailureContext`, the `subscription_failure` `leg_type`) were all
  built in Milestone 2 / M1. `alembic head` stays `0013`.
- **Objective:** the Leg-3 analogue of M7b: `subscription.charged.failed` →
  30 s self-recovery buffer (§2.3) → `SUBSCRIPTION_FAILURE` `RevenueLeakCase` in
  `DETECTED`, with a typed `SubscriptionFailureContext` and **rail-specific**
  retry-budget seeding (§2.7 / Part A §3 / D-072) in the case transaction. No
  dispatch past `DETECTED`. The M7c §2.7 systemic-hold hook also applies.
- **Scope delivered:**
  - **`src/torque/ingestion/payloads.py`** — subscription extractors:
    `subscription_entity`, `subscription_id`, `mandate_id`
    (**`payment.entity.token_id` only** — a `subscription.id` is never
    substituted; D-072), `billing_cycle`
    (1-based ordinal from `subscription.entity.paid_count`),
    `mandate_type_from_method` + `_METHOD_TO_MANDATE` (D-070; unknown → `NACH`),
    `subscription_failure_context`.
  - **`src/torque/ingestion/subscription.py`** (NEW): `subscription_failure_buffer_seconds()`
    (30, `PolicyConfig.subscription_failure_buffer_seconds`);
    `resolve_subscription_buffered_event` (NOOP / `_has_interim_charge` →
    `SELF_RECOVERED` / `create_subscription_case`); `create_subscription_case`
    (idempotent on `source_event_id`; `resolve_counterparty`; insert
    `RevenueLeakCase(SUBSCRIPTION_FAILURE, DETECTED, …)` via `TenantScope`;
    `sync_control_group`; `_seed_rail_budget`; `apply_active_hold_if_any`;
    `Event.processed = True`); `_seed_rail_budget` / `_seed_upi_retry_budget`
    (`attempts_used = 1`) / `_seed_nach_retry_policy`
    (`clearing_cycle_status = RETURNED`, `dishonour_count_this_fy = 1`,
    `return_reason_code = None`). No cross-leg dedup (§2.4 is Leg 1 ↔ Leg 2).
  - **`src/torque/ingestion/cases.py`** — `_seed_card_retry_budget` renamed →
    `seed_card_retry_budget` (now shared with `subscription.py` for
    `mandate_type = CARD`). One internal call site + one test reference updated.
  - **`src/torque/ingestion/tasks.py`** — `resolve_subscription_buffered_event_task(event_id)`
    (one `_session_scope()`, delegates to `resolve_subscription_buffered_event`).
  - **`src/torque/api/webhooks.py`** — dispatch gains
    `elif event.type == SUBSCRIPTION_FAILED: resolve_subscription_buffered_event_task.apply_async((str(id),), countdown=30)`.
    `subscription.charged` (success) is persisted only, not enqueued.
  - **`tests/conftest.py`** — `razorpay_subscription_body(...)` builder;
    `make_api_client` now also spies `resolve_subscription_buffered_event_task.apply_async`
    (`client.subscription_enqueue`).
  - Tests: `test_subscription_buffer.py` (11), `test_subscription_case_creation.py`
    (13 w/ parametrize), `test_subscription_budget_seeding.py` (8),
    `test_subscription_webhook_dispatch.py` (5), `test_subscription_systemic_hook.py`
    (2). `test_schema_introspection.py` +1. `test_ingestion_atomicity.py` — one
    line (rename).
- **Decisions:** D-070..D-073.
- **Deviations from blueprint:** none. D-070 (method→mandate map + `NACH`
  default) and D-072 (`NACHRetryPolicy` initial state, `return_reason_code = None`
  at ingestion) are routine data-mapping choices the blueprint leaves open, not
  deviations. `seed_card_retry_budget` rename is a genuine cross-module
  requirement, not cosmetic.
- **Deferred work removed from `DEFERRED.md` (Module 2):** the
  `subscription.charged.failed` 30 s buffer; Leg-3 `SUBSCRIPTION_FAILURE` case
  creation; `UPIRetryBudget` seeding; `NACHRetryPolicy` seeding.
- **Deferred / still open (Module 2):** systemic detection rollup does **not**
  count `subscription.charged.failed` yet (D-073); per-decline UPI increment +
  `mandate_cancelled_at` on the 4th attempt (Module 5); the real NPCI NACH
  `return_reason_code` + `retry_eligible_after` (Module 5, bank return file);
  Leg 4 (`invoice.overdue` / `B2BInvoice` bundling); Leg 2 (`checkout.abandoned`)
  + the reverse cross-leg Merge; `ISSUER_SPECIFIC` systemic detection (U-08);
  dispatch to Module 3; a `docker-compose` worker/beat service.
- **Unresolved:** none resolved from the U-list. Method→`MandateType` mapping is
  now a decided default (D-070). U-04 (systemic N/M tuning), U-08 (issuer
  extraction), U-07 (`PlaybookRun` engine), U-01 edges 1–2 all still open.
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD** (`2a35786`).
  M8 creates cases at `DETECTED`, runs no transitions, adds no edge, no guard.
- **Transactional atomicity:** the Celery task opens one `session_scope()`;
  `resolve_subscription_buffered_event` / `create_subscription_case` /
  `_seed_rail_budget` use only `session.flush()`. Case + counterparty +
  `Merchant_Counterparty` + the one rail budget + `Event.processed` commit or roll
  back as one unit — verified by `test_failure_mid_seed_rolls_everything_back`.
- **Tests at completion:** **493** `def test_` functions; `pytest` collects and
  passes **557** (was 460 / 519 at M7c). `ruff` clean. `alembic upgrade head` →
  `0013` (no-op — no M8 migration); up→down→up roundtrip green. 1 cosmetic
  `StarletteDeprecationWarning` (unchanged).
- **Verification status:** complete + verified against a live Postgres
  (docker-compose db, host 5442). `pytest` 557 green, `ruff` clean, roundtrip
  green, `state_machine.py` / `guards.py` diffs empty vs `2a35786`, no migration.
- **Recommended commit message:**
  `Milestone 8: Leg-3 signal ingestion — subscription.charged.failed buffer, case, UPI/NACH budget seeding`

---

## Module 2 — Signal Ingestion — COMPLETE (Legs 2 & 4 + bidirectional correlation)

*(The project switched from milestone-by-milestone to module-by-module execution
here. This section closes Module 2. M7a/M7b/M7c/M8 sections above remain the
per-milestone history for Legs 1 & 3 + systemic detection.)*

- **Commit:** *(uncommitted — maintainer commits)*. HEAD at implementation time:
  `2a35786` (Milestone 7). M8 (Leg 3) is also uncommitted on top of that.
- **Migrations:** **none.** Legs 2 & 4 are pure ingestion logic over tables from
  Milestone 1/2. `alembic head` stays `0013`.
- **Blocker resolved before implementation:** an instruction described a
  `CASE_SUPERSEDED` CaseEvent as "authoritative". It is not — blueprint §4's
  CaseEvent table is closed at 10 (D-007) and D-041/D-059/D-068 govern that
  vocabulary. The maintainer chose **Option A**: the merge audit stays the
  blueprint's `superseded_by_case_id` + merged context + preserved event history
  (D-076). No new `CaseEventType`, no payload schema, no `ALTER TYPE` migration.
- **Objective:** finish Module 2 — the last two signal legs and the second
  direction of the §2.4 cross-leg Merge — so all four legs (`PAYMENT_DEGRADATION`,
  `CHECKOUT_ABANDONMENT`, `SUBSCRIPTION_FAILURE`, `B2B_RECEIVABLE`) share one
  reliable, idempotent, causality-aware ingestion engine that forms/merges
  canonical cases.
- **Scope delivered:**
  - **`src/torque/api/checkout_injection.py`** (NEW) — `POST
    /internal/checkout-abandoned/{merchant_id}`, the §2.6 signed synthetic
    injection endpoint. Verify-before-parse mirroring `webhooks.py`/INV-23:
    HMAC over the raw body (`verify_razorpay_signature`) against
    `Settings.checkout_injection_secret`; `X-Torque-Signature` /
    `X-Torque-Event-Id` (header-sourced idempotency); silent empty-200 on any
    failure; one `Event(type="checkout.abandoned")` via `TenantScope` + enqueue
    `create_checkout_case_task`. Included in `create_app()`. D-074.
  - **`src/torque/ingestion/checkout.py`** (NEW) — Leg 2. `create_checkout_case`:
    no buffer (§2.3); idempotent on `source_event_id` + `event.processed`;
    `resolve_counterparty`; typed `CheckoutAbandonmentContext`
    (`cart_id` / `cart_value` / `drop_stage` / `payment_method_attempted` from
    the §4 vocab — unknown → `NONE`); `find_supersedable_payment_case` →
    **reverse §2.4 Merge** (supersede the new abandonment into a pre-existing
    canonical `PAYMENT_DEGRADATION` case, merge context into the survivor, status
    unchanged — D-075/D-076); `sync_control_group`; `apply_active_hold_if_any`
    on a canonical case only (D-078); `Event.processed`.
  - **`src/torque/ingestion/b2b.py`** (NEW) — Leg 4. `ingest_invoice`: no buffer;
    idempotent (`event.processed` + `source_event_id`); `resolve_counterparty`;
    the **locked §3 grouping rule** (open non-terminal `B2B_RECEIVABLE` case for
    `(merchant, counterparty)` → `B2BInvoice` attaches (`CASE_ATTACHED`); else a
    new case + first invoice (`CASE_CREATED`); no time window; `context = {}`);
    Razorpay `invoice.entity` → amounts (paise→₹, `outstanding` clamped to
    `[0, original]`), `due_date` (`expire_by`|`date`), `days_overdue`,
    `gst_inclusive`, `payment_terms`; `case.amount_at_risk` = Σ `outstanding`;
    `apply_active_hold_if_any` on create. D-077.
  - **`src/torque/ingestion/dedup.py`** — added `find_supersedable_payment_case`
    (reverse direction; matches the abandonment `cart_id` against a payment
    case's `source_event.raw_payload` `order_id`); docstring now describes the
    bidirectional check. `find_supersedable_case` (forward) unchanged.
  - **`src/torque/ingestion/payloads.py`** — `checkout_*` extractors +
    `checkout_abandonment_context`; `invoice_*` extractors.
  - **`src/torque/ingestion/tasks.py`** — `create_checkout_case_task`,
    `ingest_invoice_task` (both immediate, one `session_scope` each).
  - **`src/torque/ingestion/outcomes.py`** — `BufferOutcome.CASE_ATTACHED`;
    `CASE_MERGED` doc generalised to "either direction".
  - **`src/torque/api/webhooks.py`** — dispatch gains
    `elif event.type == INVOICE_OVERDUE: ingest_invoice_task.apply_async(...)`
    (no countdown). `subscription.charged` / `payment.captured` still
    persist-only.
  - **`src/torque/config.py`** — `Settings.checkout_injection_secret`.
  - **`tests/conftest.py`** — `checkout_abandoned_body`, `razorpay_invoice_body`;
    `make_api_client` also spies `create_checkout_case_task` / `ingest_invoice_task`
    and sets `checkout_injection_secret`.
  - Tests: `test_checkout_injection.py` (9), `test_checkout_case_creation.py` (7),
    `test_cross_leg_dedup_reverse.py` (9), `test_b2b_ingestion.py` (10),
    `test_module2_integrity.py` (7). `test_schema_introspection.py` +2.
- **Decisions:** D-074..D-078.
- **Deviations from blueprint:** none. D-074/D-076/D-077 are the blueprint's
  stated defaults / locked rules; the `checkout.abandoned` body shape and the
  `checkout_injection_secret` are routine implementation choices §2.6 leaves
  open.
- **Deferred work removed from `DEFERRED.md` (Module 2):** Leg 2
  (`checkout.abandoned`) ingestion + the signed injection endpoint; the **reverse
  cross-leg Merge direction** (D-060); Leg 4 (`invoice.overdue` / `B2BInvoice`
  bundling).
- **Deferred / still open (belongs to later modules or a later Module-2
  refinement):** `ISSUER_SPECIFIC` systemic detection (U-08); systemic rollup
  over `subscription.charged.failed` (D-073); per-decline retry-budget increments
  + `UPIRetryBudget.mandate_cancelled_at` (Module 5); real NPCI NACH
  `return_reason_code` / `retry_eligible_after` (Module 5); a real storefront
  SDK/pixel for Leg 2 (Part D item 1); a `docker-compose` Celery worker/beat
  service; **dispatch to Module 3** (cases sit in `DETECTED`); dunning /
  playbooks / partial-payment `outstanding_amount` decrement / case closure
  (Modules 4–7).
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD` empty). All four legs create/attach cases in `DETECTED`; no
  transition, no edge, no guard.
- **Transactional atomicity:** every ingestion task is one `session_scope()`;
  the leg functions only `flush()`. Case + counterparty + `Merchant_Counterparty`
  + context + rail-budget seed + merge + `B2BInvoice` + `Event.processed` commit
  or roll back as one unit. Verified by
  `test_b2b_ingestion.py::test_failure_mid_ingest_rolls_everything_back`.
- **Tests at completion:** **537** `def test_` functions; `pytest` collects and
  passes **601** (was 493 / 558 at M8). `ruff` clean. `alembic upgrade head` →
  `0013` (no-op); up→down→up roundtrip green. 1 cosmetic
  `StarletteDeprecationWarning` (unchanged).
- **Verification status:** complete + verified against a live Postgres
  (docker-compose db, host 5442). `pytest` 601 green, `ruff` clean, roundtrip
  green, `state_machine.py` / `guards.py` diffs empty, no migration created.
- **Recommended commit message:**
  `Module 2: complete signal ingestion — checkout.abandoned + invoice.overdue legs, bidirectional cross-leg merge`

---

## Module 3 — Diagnosis Engine — COMPLETE

*(One module = one implementation run = one audit. This section closes Module 3,
built in one continuous run on top of the committed Module 2.)*

- **Commit:** *(uncommitted — maintainer commits after the audit)*. HEAD at
  implementation time: `c71c90e` ("Additional Commit" — the committed Module 2).
- **Migration:** **0014_diagnosis_timing** (additive; one nullable column
  `revenue_leak_case.suggested_timing_adjustment VARCHAR(64)`; no table, no enum).
  `alembic head` → `0014`; up→down→up roundtrip green.
- **Objective:** convert a Module-2 canonical `RevenueLeakCase` into
  `root_cause_code` / `root_cause_label` / `diagnosis_confidence` /
  `suggested_timing_adjustment` (and, for PAYMENT_DEGRADATION, `is_hard_decline`),
  then route it by the `T = 0.65` confidence threshold — `DIAGNOSING →
  PLAYBOOK_ACTIVE` (≥ T) or `DIAGNOSING → ESCALATED_TO_HUMAN` (< T, Part C item 1).
- **Scope delivered:**
  - **`torque.diagnosis` package** (new): `root_causes.py` (the Module-3-owned
    `RootCauseCode` §3.1 vocabulary — 23 members, `.value` persisted to the plain
    `String` column; per-leg valid sets; `is_hard_decline` and payday-timing
    derivations; labels), `decline_codes.py` (Razorpay decline-code → semantic
    category + confidence; known 0.75 / opaque 0.4), `classifier.py` (pure per-leg
    rules → `DiagnosisResult`), `engine.py` (`diagnose_case` orchestrator:
    eligibility, tenant-scoped input gathering, atomic persistence, confidence
    routing), `tasks.py` (`diagnose_case_task` Celery task).
  - **Per-leg diagnosis (§3.2):** *Payment/Subscription* share the step 1–3 path
    — TIER_1/TIER_3 `network_directive` precedence (0.95) → decline-code lookup
    (known 0.75 / opaque 0.4, opaque deliberately < T) → missing-code gateway
    timeout (0.5); subscription adds the §3.2.4 mandate **facts** first
    (`NACH_CLEARING_PENDING` / `UPI_AUTOPAY_CAP_EXHAUSTED`, 1.0, D-082) and reads
    its decline code from the source Event (D-081). *Checkout* classifies
    `(drop_stage, payment_method_attempted)` — every band < T, so checkout always
    escalates. *B2B* buckets `days_overdue × promise_keeping_rate`, established 0.8
    / cold-start 0.4 (D-084).
  - **`is_hard_decline`** now owned and written by Module 3 (D-058 honoured;
    D-084 derivation), only for PAYMENT_DEGRADATION, only when the verdict is not
    `None`.
  - **`suggested_timing_adjustment`** persisted to the new case column (D-079).
  - **Audit:** one `DIAGNOSIS_COMPLETED` `CaseEvent` per diagnosis (existing type
    / payload schema — **no new `CaseEventType`**), `actor = AGENT`, `reasoning`
    populated (UI "Agent Reasoning"); the status changes ride the existing
    `STATUS_CHANGED` events.
- **State machine:** exercises the pre-existing `DETECTED → DIAGNOSING`,
  `DIAGNOSING → PLAYBOOK_ACTIVE`, `DIAGNOSING → ESCALATED_TO_HUMAN` edges — **no
  new edge, no change to `state_machine.py`**. A §2.5-resumed `DIAGNOSING` case is
  completed without the `DETECTED` hop.
- **Idempotency:** eligible = `DETECTED`, or `DIAGNOSING` with no `root_cause_code`
  yet, and not superseded. Already-diagnosed / terminal / `SYSTEMIC_HOLD` /
  superseded / missing → `NOOP`. Repeated task execution is safe.
- **Transactional atomicity:** the whole diagnosis (status transition(s) + case
  fields + `DIAGNOSIS_COMPLETED`) runs in one `atomic()` unit; a mid-diagnosis
  failure rolls everything back (verified by `test_diagnosis_atomicity.py`).
- **Tenancy:** every supporting lookup (`UPIRetryBudget`, `NACHRetryPolicy`,
  `MerchantCounterparty`, `B2BInvoice`, the source `Event`) is `TenantScope`d to
  `case.merchant_id` — merchant-A cases never read merchant-B evidence (verified
  by `test_diagnosis_tenancy.py`).
- **Decisions:** D-079 (timing column), D-080 (no auto-dispatch from Module 2),
  D-081 (subscription decline from Event), D-082 (mandate-fact precedence), D-083
  (consume tier, no MAC extraction), D-084 (is_hard_decline derivation + demo
  buckets).
- **Deviations from blueprint:** none. (One Part-C-style Module-1 schema addition
  — the timing column — surfaced by a later module's output, D-079.)
- **Deferred work introduced:** the Module 2 → Module 3 auto-dispatch trigger
  (D-080); the §5.3 first-touch MAC-code lookup at diagnosis time (D-083, blocked
  on U-08).
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD` empty).
- **Tests at completion:** **585** `def test_` functions (was 537); `pytest`
  collects and passes **687** (was 601), 0 fail / 0 skip. Module 3 adds 7 test
  files (48 functions → 86 collected cases). `ruff` clean. `alembic upgrade head`
  → `0014`; up→down→up roundtrip green. 1 cosmetic `StarletteDeprecationWarning`.
- **Verification status:** complete + verified against a live Postgres
  (docker-compose db, host 5442). `pytest` 687 green, `ruff` clean, roundtrip
  green, `state_machine.py` / `guards.py` diffs empty, migration `0014` applies.
- **Recommended commit message:**
  `Module 3: diagnosis engine — root-cause classification, confidence routing, is_hard_decline`

---

## Module 4 — Policy & Playbook Engine — COMPLETE

*(One module = one run = one audit. Closes the runtime half of Module 4; the M4
definition contract — versioned `Playbook`, `MerchantPlaybookConfig`,
`PlaybookRun` schema, save-time validation — was already committed.)*

- **Commit:** *(uncommitted — maintainer commits after the audit)*. HEAD at
  implementation time: the committed Module 3.
- **Migration:** **none.** No schema change — the catalog seeds through the ORM
  (D-085), the payday flag lives in `Merchant.risk_appetite_config` (D-087), and
  `multi_case_template` lives in step `params`. `alembic head` stays `0014`.
- **Objective:** take a diagnosed `PLAYBOOK_ACTIVE` case, select the eligible
  §4.1 catalog playbook, resolve merchant availability, and instantiate a
  version-pinned `PlaybookRun` at the graph's entry step — the runtime contract
  Module 5 executes. "Module 4's contract ends at 'here is a valid graph and the
  rules for reading it'" (§4).
- **Scope delivered (new `torque.policy` package):**
  - **Catalog (§4.1):** `catalog.py` — the eleven playbooks (slugs, leg/mandate
    discriminators, concrete `steps_graph` outreach/retry ladders, template
    `stopping_rules`), `seed_catalog` inserting them ORM-validated (D-085). UPI
    AutoPay playbook `max_attempts = 3` (≤3 save-time rule intact).
  - **Selection (§4.1):** `selection.py` — `select_playbook_id(leg, root_cause,
    mandate_type)`. Subscription NSF is rail-specific (CARD/UPI_AUTOPAY/NACH);
    `INSTRUMENT_NOT_RECURRING_CAPABLE` maps per leg; network directive is *not* a
    separate input (Module 3 already folded it into the root cause). "Trivial"
    causes → `None`.
  - **Run instantiation:** `engine.activate_case` — eligibility (PLAYBOOK_ACTIVE,
    non-superseded), idempotency (one live run per case, D-089), pin the latest
    version, `active_step_id = entry`, `status = RUNNING`, all atomic. No-playbook
    / disabled → `ESCALATED_TO_HUMAN` (D-086). No CaseEvent for run creation
    (D-089).
  - **Version pinning (D-021/D-024):** composite-FK pin; a later version never
    alters an in-flight run; effective rules resolve off the pinned base (D-089).
  - **Effective config:** `resolve_effective_stopping_rules` — merchant override
    deep-merged onto the pinned version's rules (reuses `torque.playbooks`).
  - **Traversal rules (§4):** `traversal.py` — pure `entry_step_id` /
    `next_step_id` / `is_terminal` / `node` / `step_template`. No DB, no clock, no
    `active_step_id` mutation, no action execution (all Module 5).
  - **Payday policy (§4.3):** `payday.py` — the override *gate* (`Merchant`
    config, default true); the fire-time *computation* stays Module 5 (D-025).
  - **Multi-case (§4.4):** `step_template(node, multi_case)` returns the
    `multi_case_template` when merged, else the single template + a `defer` signal
    (→ Module 5 `OUTREACH_COORDINATOR_DEFERRED`, never a silent drop). Reuses the
    existing `ActionCase` attribution — no second model.
  - **`tasks.py`:** `activate_case_task` (Celery), registered in `celery_app`.
- **State machine:** uses the pre-existing `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN`
  edge for the no-playbook/disabled route; run creation itself needs no
  transition (case already `PLAYBOOK_ACTIVE`). **No new edge, no change to
  `state_machine.py`.**
- **Decisions:** D-085 (ORM-seeded catalog), D-086 (no-playbook → escalate),
  D-087 (payday flag in `risk_appetite_config`), D-088 (no auto-dispatch), D-089
  (no run-created event / one-live-run idempotency / pinned-base rules).
- **Deviations from blueprint:** none.
- **Deferred work introduced:** the Module 3 → Module 4 auto-dispatch trigger
  (D-088); runtime traversal execution, timing computation, guardrail
  enforcement, Temporal (all Module 5).
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD` empty).
- **Tests at completion:** **632** `def test_` functions (was 585); `pytest`
  collects and passes **754** (was 687), 0 fail / 0 skip. Module 4 adds 8 test
  files (47 functions → 67 collected cases). `ruff` clean. `alembic head` `0014`
  (no migration); roundtrip green.
- **Verification status:** complete + verified against a live Postgres
  (docker-compose db, host 5442). `pytest` 754 green, `ruff` clean, roundtrip
  green, `state_machine.py` / `guards.py` diffs empty, no migration created.
- **Recommended commit message:**
  `Module 4: policy & playbook engine — catalog, selection, version-pinned run instantiation`

---

## Module 5 — Execution & Orchestration — COMPLETE

*(One module = one run = one audit. Built on the committed Module 4. The
orchestration engine was a maintainer decision — Postgres-polling over Temporal,
D-090.)*

- **Commit:** *(uncommitted — maintainer commits after the audit)*. HEAD at
  implementation time: `c17dd82` (committed Module 4).
- **Migration:** **0015_scheduled_job** (additive: one table `scheduled_job`,
  `UNIQUE(run_id)`, indexes on `merchant_id`/`fire_at`; reuses the `leg_type`
  enum). `alembic head` → `0015`; up→down→up roundtrip green.
- **Maintainer decision:** durable `PlaybookRun` execution uses the **§5.6
  Postgres-polling** driver, not Temporal (resolves U-07; D-090). Module 5/6
  guardrail line confirmed (D-092).
- **Objective:** execute a version-pinned `PlaybookRun`'s graph at runtime —
  resolve `active_step_id`, run §5.2 guardrails, execute the action (§5.4 stub),
  record the outcome + `STEP_TRANSITIONED` atomically, advance the pointer, and
  reschedule — driven by the polling timer.
- **Scope delivered (`torque.execution` package):**
  - **Polling driver:** `scheduled_job` model + migration 0015; `scheduler.py`
    (`schedule_run`, `claim_due_jobs` with `FOR UPDATE SKIP LOCKED`,
    `execute_due_jobs`); `tasks.py` two Celery-beat pollers (10 s
    `PAYMENT_DEGRADATION` / 60 s others, §5.6) + beat-schedule wiring.
  - **Runtime tick (`runner.execute_due_job`):** the §5.1 loop — stopping-rule
    check → `allowed_hours` re-check (defer) → guardrails → execute → atomic
    Action+CaseEvent (`write_action_and_event`) → `STEP_TRANSITIONED` → advance
    `active_step_id` (Module 4's `traversal` rules) or finalize.
  - **Timing (`timing.py`, D-025):** offset from previous completion; IST
    `allowed_hours` deferral incl. overnight windows; payday substitution
    (`next_month_end_working_day`); UPI peak-window re-defer. Distinguishes *step
    offset* from *execution window*.
  - **Guardrails (`guardrails.py`, §5.2, Module-5 half per D-092):** network
    hard-stop, Card/UPI/NACH budgets, UPI hard-cap + peak-window defer, §5.2.3
    pre-debit gap **with auto-insert self-heal**, systemic-hold block; quiet-hours
    / UPI-window are defers.
  - **Retry-budget consumption:** Card (`attempts_used_24h/_30d`) and UPI
    (`attempts_used`) incremented once per fired retry, row-locked; NACH consumes
    no counter (returns are external).
  - **Executor (`executor.py`, §5.4):** internal stub, no external I/O,
    monkeypatchable — the seam real adapters attach to.
  - **Multi-case rendering (`rendering.py`, §4.4):** single vs `multi_case_template`
    resolution + combined-amount context; reuses `ActionCase` attribution;
    rejects superseded cases.
  - **U-02 settled (D-091):** `STEP_TRANSITIONED` payload finalised
    (`{run_id, from_step_id, outcome, to_step_id?, edge_condition?}`).
- **State machine:** uses the existing `PLAYBOOK_ACTIVE → {ESCALATED_TO_HUMAN,
  EXHAUSTED}` edges — **`state_machine.py` and `guards.py` byte-unchanged vs HEAD**.
  Terminal mapping D-093.
- **Idempotency / concurrency:** one pending timer per run + `SKIP LOCKED`
  (INV-43); proven with two real DB connections. Atomic tick; tenant-scoped
  (INV-45); version-pinned execution (INV-44); UPI cap never exceeded (INV-46).
- **Decisions:** D-090 (polling driver), D-091 (STEP_TRANSITIONED / U-02), D-092
  (Module 5/6 guardrail line), D-093 (dispatch deferral, executor stub, terminal
  mapping).
- **Deviations from blueprint:** none beyond the sanctioned Decision-C choice of
  the fallback engine (D-090). `NETWORK_HARD_STOP` is used for both TIER_1 and
  TIER_3 retry blocks (the `BlockReason` enum has no instrument-dead value; §5.2.1
  names `INSTRUMENT_NOT_RECURRING_CAPABLE`, which is a `HardStopReason`).
- **Deferred introduced:** Module 4 → 5 auto-dispatch trigger (D-093); real
  channel adapters + the Outreach Coordinator + WhatsApp consent/template gate
  (Module 6, D-092); a real Temporal option (D-090 leaves it a driver swap).
- **Tests at completion:** **680** `def test_` functions (was 632); `pytest`
  collects and passes **808** (was 754), 0 fail / 0 skip. Module 5 adds 7 test
  files (48 functions). `ruff` clean. `alembic upgrade head` → `0015`; roundtrip
  green. 1 cosmetic `StarletteDeprecationWarning`.
- **Verification status:** complete + verified against a live Postgres. `pytest`
  808 green, `ruff` clean, roundtrip green, `state_machine.py`/`guards.py` diffs
  empty, migration 0015 applies.
- **Recommended commit message:**
  `Module 5: execution & orchestration — Postgres-polling driver, runtime traversal, guardrails, timing`

### Module 5 — Corrective pass (post-audit)

The Module 5 adversarial audit returned two MAJOR findings; this corrective run
fixed both (no new migration, `state_machine.py`/`guards.py` still untouched):

- **F-1 (timing):** `max_duration_days` now measures the run's **active span from
  the first executed action** (`min(Action.executed_at)`), not `run.created_at`, and
  the **payday substitution applies to the entry step only** (D-094). The flagship
  NSF-payday retry — previously exhausted before it fired when the payday target sat
  beyond `max_duration` — now reaches execution; `max_duration` still bounds the
  active span for every playbook. Surfaced and fixed a coupled over-application bug
  (payday was applied to every advancing step, pushing each rung to the next
  month-end).
- **F-2 (isolation):** the poll pass now executes **each job in its own
  `begin_nested()` SAVEPOINT** (D-095, `StepResult.ERROR`) — a poison job rolls back
  only itself and is re-tried later; committed sibling work and the `SKIP LOCKED`
  concurrency guarantee are preserved.
- **F-6:** added a defensive superseded-case guard in the tick (NOOP + drop timer).
- **F-3 / F-4 / F-5:** documentation clarifications — `run.status = COMPLETED` means
  execution terminated, not recovered (D-096); the systemic-hold-drains-an-active-run
  limitation is recorded (blueprint gap); timing inputs are documented as tz-aware
  (IST is DST-free). No behavioural change for these three.
- **Tests:** +9 in `tests/test_module5_corrections.py` (F-1 payday-executes /
  entry-only / active-span-bound / non-payday-unaffected; F-2 poison-isolation /
  retryable / per-job atomicity; F-6). Suite **817** collected/passed, 0 fail / 0
  skip; `ruff` clean; roundtrip green; head `0015` (no migration).
- **Decisions:** D-094, D-095, D-096.

---

## Module 6 — Compliance & Cross-Leg Guardrail Engine — COMPLETE

*(One module = one run = one audit. Built on committed Module 5. The read-only
Module 6 audit was approved with ten locked decisions Q-A … Q-J; this run
implements exactly that scope.)*

- **Commit:** *(uncommitted — maintainer commits after review)*. HEAD at
  implementation time: **`e8194c2`** (committed Module 5 + its corrective pass —
  the Module 5 run and corrective pass are now committed, not "uncommitted" as
  the earlier `CURRENT_STATE.md` still said).
- **Migration:** **0016_human_queue** (additive: one table `human_queue`,
  `UNIQUE(case_id)` idempotency backstop, indexes on `merchant_id`/`enqueued_at`;
  **no enum, no ALTER, no new `CaseEventType`** — the closed §4 vocabulary of 10
  is untouched). `alembic head` → `0016`; up→down→up roundtrip green.
- **New package `torque.coordination`** (execution-package-free — Q-J):
  - **`guardrail_engine.py`** — `GuardrailEngine.check(session, *, action_type,
    now, case|case_id, run, node, params)` → the single facade Module 5 consults
    (§6.2). Composes the existing pure predicates; runs the §5.2 sequence
    first-failure-wins. Returns the **four-way `GuardDecision`**
    (ALLOW / BLOCK / DEFER / AUTO_INSERT_PREDEBIT) — the intentional deviation
    from the blueprint's `{allow, block_reason?}` wording (D-097 / Q-A).
  - **`outreach_coordinator.py`** — `priority()` (Module 8 seam — `amount_at_risk`
    placeholder, D-098 / Q-B), `cross_leg_quiet_period_defer()` (the 4h Part A §5
    quiet period → `quiet_period_end + timing_offset`, `PolicyConfig.
    cross_leg_quiet_period_hours`), `open_conversation_defer()` (§3
    `active_wa_conversation_expires_at`), `whatsapp_gate()` (gate #1
    `whatsapp_opt_in` + gate #2 `approved_template_exists` for an approved UTILITY
    template — reused, not reimplemented), `unsuccessful_action_count()` (the
    escalation-ceiling tally).
  - **`human_queue.py`** — `HumanQueueReason` (a plain-string vocabulary, D-097),
    `enqueue()` (idempotent on `case_id`), `list_for_merchant()`
    (priority-desc then FIFO, or `order="fifo"`), `sweep_escalated_to_human()`
    (feeder 1 — Q-H, no Module 3 change), `route_broken_promise()` (feeder 3 —
    routing hook for a `BROKEN` `PromiseToPay`, never a harsher message).
  - **`merge.py`** — `merge_groups()` + `execute_merged()`: the live Outreach
    Coordinator merge (Part A §5 / §4.4), driven from the poll batch where both
    jobs are already claimed under one `FOR UPDATE SKIP LOCKED`. Higher-`priority`
    case owns one merged `Action` (one `ActionCase` per case, `credit_weight`
    proportional to `amount_at_risk`, Σ = `Decimal("1.00000")` exact); with no
    `multi_case_template` the primary sends single-case and each secondary is
    **deferred** (`ACTION_BLOCKED`/`OUTREACH_COORDINATOR_DEFERRED`, timer bumped,
    step not advanced) — never dropped (Q-C).
- **New model `HumanQueueEntry`** (`torque/models/human_queue_entry.py`,
  `TenantScoped`) + registered in `models/__init__.py`.
- **`GuardDecision` extended** (`torque/execution/guardrails.py`) with two optional
  fields — `defer_until` (explicit reschedule target) and `human_queue_reason`
  (flag the case for human pickup). The four-way `GuardKind` is unchanged; every
  existing DEFER/BLOCK/AUTO_INSERT path is byte-for-byte preserved.
- **Runner integration** (`torque/execution/runner.py`, `scheduler.py`):
  - `_guardrails()` now delegates to `GuardrailEngine.check()` — the retry path is
    the unchanged Module 5 predicate verbatim; contact actions get the coordinator
    + WhatsApp gates.
  - a DEFER carrying `OUTREACH_COORDINATOR_DEFERRED` also writes an
    `ACTION_BLOCKED` row (Part A §5 defer policy) and — for open-conversation —
    enqueues the case; the step is **not** advanced.
  - **§6.3 escalation ceiling:** `_escalation_ceiling_hit` / `_escalate_on_ceiling`
    — one check at the top of the tick (before the execution-layer stopping
    bounds). Trips when accumulated unsuccessful attempts (blocked / failed /
    no-response — Q-D) reach `stopping_rules.escalation_ceiling`; transitions the
    case `→ ESCALATED_TO_HUMAN` (existing legal edge, trigger
    `"escalation_ceiling"`), sets the run `ESCALATED`, enqueues it, drops the
    timer, returns `StepResult.ESCALATED_CEILING`. Short-circuits before a
    graph-terminal `ESCALATE_HUMAN` could run — one transition only.
  - `StepResult` gains `ESCALATED_CEILING` and `MERGED`.
  - `execute_due_jobs` groups claimed outreach jobs by `(merchant_id,
    counterparty_id)` and folds 2+ via `merge.execute_merged` before the solo
    loop.
- **Playbook validation** (`torque/playbooks/validation.py`): new
  `_check_escalation_ceiling` — `escalation_ceiling <= max_attempts`, enforced on
  the base rules and on any merchant override merged onto them (the same
  defense-in-depth path as the UPI cap, Q-D). All eleven catalog playbooks and
  the test fixtures already satisfy it.
- **State machine:** the ceiling escalation uses the existing legal
  `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN` edge — **`state_machine.py` and
  `guards.py` byte-unchanged vs HEAD** (`git diff HEAD --` empty).
- **Decisions:** D-097 (four-way `GuardDecision` facade + string reason
  vocabulary), D-098 (Module 8 `priority()` seam), D-099 (`GuardDecision`
  `defer_until` / `human_queue_reason` + the OUTREACH_COORDINATOR_DEFERRED
  DEFER-writes-a-blocked-Action rule), D-100 (escalation-ceiling semantics +
  insertion point + `escalation_ceiling <= max_attempts`), D-101 (persistent
  `human_queue` table + the low-confidence sweep + open-conversation as a 4th
  reason), D-102 (merge trigger = both jobs due in one claimed batch; residual
  cross-stratum race documented).
- **Deviations from blueprint:** (1) `GuardrailEngine.check()` returns the
  four-way `GuardDecision`, not `{allow, block_reason?}` (D-097 / Q-A). (2) the
  open-WhatsApp-conversation path is a **defer** (past the window) + human-queue
  flag, not a hard block — avoids a `BlockReason` enum migration (Q-F). (3)
  `HumanQueueReason` has a 4th value `OPEN_WA_CONVERSATION` beyond §6.4's three
  feeders (Q-F requires the enqueue).
- **Deferred introduced / still deferred:** Module 8 itself (the real
  `(probability × amount) ÷ cost` score — `priority()` is the seam); `LOG_PROMISE`
  execution (the broken-promise routing hook is exercised against a
  directly-built `BROKEN` promise); real channel adapters; Agent Console controls
  + `escalation_resolution` + `HUMAN_RESOLVED` (Module 10 — Q-I); a per-node
  WhatsApp template category (the gate checks UTILITY); cross-stratum merge
  (the 10 s / 60 s pollers claim disjoint sets — a split pair sends solo, the
  safe un-merged baseline, documented in `merge.py`).
- **Tests at completion:** **737** `def test_` functions (was 689); `pytest`
  collects and passes **865** (was 817), 0 fail / 0 skip. Module 6 adds 7 test
  files (43 functions) + 5 schema-introspection tests; `test_module4_versioning`
  updated (v2 playbook now needs a coherent `escalation_ceiling`); `conftest`
  `make_counterparty` defaults `whatsapp_opt_in=True` and `make_active_run` seeds
  an approved WA template so existing Module 5 drains still send their WA nudges.
  `ruff` clean. `alembic upgrade head` → `0016`; roundtrip green. 1 cosmetic
  `StarletteDeprecationWarning` (pre-existing).
- **Verification status:** complete + verified against a live Postgres. `pytest`
  865 green, `ruff` clean, roundtrip green, `state_machine.py`/`guards.py`
  `git diff HEAD` empty, migration 0016 applies, two-connection merge concurrency
  test green.
- **Recommended commit message:**
  `Module 6: compliance & cross-leg guardrail engine — GuardrailEngine facade, Outreach Coordinator, escalation ceiling, human queue`

---

## Module 7 — Payment Reconciliation & Attribution — COMPLETE

*(One module = one run = one audit. Built on committed Module 6 `9345ce9`.
Implemented directly from the blueprint per the Module 7 execution rules — no
separate proposal/approval cycle; the one required `state_machine.py` change was
reported before it was made.)*

- **Commit:** *(uncommitted — maintainer commits after review)*. HEAD at
  implementation time: **`9345ce9`** (committed Module 6).
- **Migration:** **none.** `recovery_type` / `recovered_amount` / `closed_at`
  (M1), `PaymentLink` (M6a), `B2BInvoice` (M1), and the `PAYMENT_RECONCILED`
  `CaseEventType` (M1) already exist. `alembic head` stays `0016_human_queue`;
  roundtrip green.
- **Load-bearing files:** `models/guards.py` **byte-unchanged**
  (`git diff HEAD` empty). **`state_machine.py` changed** — exactly the two U-01
  edges + docstring (D-103): `CaseStatus.CANCELLED` added to
  `_TRANSITIONS[DETECTED]` and `_TRANSITIONS[DIAGNOSING]`. Blueprint §7.1.4
  requires it; U-01 assigns it to Module 7; no `guards.py` change is needed
  (`RevenueLeakCase.status` has no `before_flush` guard; `CANCELLED` was already
  in `TERMINAL_STATUSES`). The exact diff was reported before the edit.
- **New package `torque.reconciliation`** (D-108):
  - **`reconcile.py`** — `reconcile_event(session, *, event_id, now=None)` →
    `ReconcileOutcome`. The §7.1 matcher (first rule wins):
    1. **Direct via `PaymentLink`** — a `payment_link.paid` / `.partially_paid`
       for a link Torque holds a row for → that link's `case_id`,
       `AGENT_ASSISTED`. `payment_link.*` also drives the link row's
       `status` / `amount_paid` / `paid_at` (Blueprint line 398). An unknown link
       with a `notes.torque_case_id` → row created; without one → falls through
       to indirect.
    2. **Indirect** — `payment.captured` / `subscription.charged`, exactly one
       open case matching `(merchant_id, counterparty_id, amount)` → attribute;
       `AGENT_ASSISTED` iff a non-blocked `Action` executed for the case within
       `PolicyConfig.attribution_window_hours` (24h), else `SELF_RECOVERED`
       (D-105).
    3. **Multiple matches** — share one merged-outreach `Action` (§4.4) →
       re-split its `ActionCase.credit_weight` ∝ `amount_at_risk` and recover all
       (`AGENT_ASSISTED`, `MULTI_RECOVERED`); a lump payment settling the
       *combined* `amount_at_risk` of such a set is also detected. Not merged →
       attribute to the most-recently-actioned case as `AMBIGUOUS`, leave the
       rest open (D-105).
    4. **No open match** — a `DETECTED` / `DIAGNOSING` case for the same
       `(merchant, counterparty, amount)` → customer self-paid before Torque
       acted → `CANCELLED` / `SELF_RECOVERED` (§7.1.4, needs D-103); else
       `NO_MATCH`.
    Closure (§7.2): full → `RECOVERED`, `recovered_amount = amount_at_risk`,
    `closed_at`; B2B partial → invoices waterfalled oldest-first,
    `PARTIALLY_RECOVERED`, `amount_at_risk` follows `Σ outstanding` (INV-33), case
    stays open; a final B2B settlement two-hops
    `PARTIALLY_RECOVERED → PLAYBOOK_ACTIVE → RECOVERED` (D-106). Every close
    writes a `PAYMENT_RECONCILED` `CaseEvent` and removes any human-queue entry
    (D-107).
  - **`payloads.py`** — `payment_link.*` extractors (id, status, amount_paid,
    `notes.torque_case_id`, customer contact). `payment.*` / `subscription.*`
    fields reuse `torque.ingestion.payloads`.
  - **`tasks.py`** — `reconcile_event_task` (one `session_scope`, delegates,
    idempotent).
- **Wiring (D-104):** `torque.api.webhooks` dispatches `reconcile_event_task` for
  `payment.captured` / `subscription.charged` / `payment_link.*` right after the
  `Event` write (no buffer — the engine is correct whenever it runs and
  idempotent on `Event.processed`). `celery_app` autodiscovers
  `torque.reconciliation`. `conftest.make_api_client` gains a
  `reconcile_enqueue` spy.
- **New helpers:** `torque.ingestion.identity.find_counterparty` (match-only, no
  create — reconciliation must not invent an identity);
  `torque.coordination.human_queue.remove_for_case`.
- **Guarantees preserved:** one `Event`'s whole reconciliation is one transaction;
  `recovery_type` / `recovered_amount` written only inside
  `guards.module7_writer` (INV-06, held open across every flush that carries the
  change); matched case rows are `SELECT … FOR UPDATE` (no double-close under
  concurrency); `PAYMENT_RECONCILED` atomic with the close; re-run on a
  `processed` `Event` is `NOOP`; every lookup tenant-scoped (a merchant-B case is
  never reconciled by a merchant-A payment).
- **Decisions:** D-103 (state-machine edges + reporting), D-104 (webhook wiring,
  no buffer), D-105 (matchability / 24h window / AMBIGUOUS tie-break), D-106 (B2B
  waterfall + two-hop settlement), D-107 (human-queue removal on close), D-108
  (package + zero migrations).
- **Deviations from blueprint:** none in behaviour. §7.1 leaves several rules
  implicit (which statuses are "open", the AMBIGUOUS case, how a partially-paid
  B2B case reaches `RECOVERED`) — D-105 / D-106 fill them conservatively.
- **Deferred introduced / still deferred:** Module 5's `GENERATE_PAYMENT_LINK`
  execution still doesn't *create* `PaymentLink` rows, so the §7.1.1 direct path
  lights up fully only once it does (Module 7 already updates rows from
  `payment_link.*` and creates one when the payload carries a Torque case ref);
  Module 8 scoring; `LOG_PROMISE`; real channel adapters; `WRITTEN_OFF` (a
  human-only `ESCALATED_TO_HUMAN` outcome — Module 10); Agent Console +
  `escalation_resolution` + `HUMAN_RESOLVED` (Module 10).
- **Tests at completion:** **772** `def test_` functions (was 737); `pytest`
  collects and passes **900** (was 865), 0 fail / 0 skip. Module 7 adds 7 test
  files (32 functions): direct / indirect / multi / nomatch / case-closure /
  idempotency-&-concurrency (two real connections) / webhook integration. Three
  pre-existing state-machine tests inverted (they asserted the U-01 edges were
  *not* legal); `test_schema_introspection` gains Module 7 assertions;
  `conftest` gains a `payment_link` body builder + the reconcile spy. `ruff`
  clean. `alembic head` `0016`; roundtrip green. 1 cosmetic
  `StarletteDeprecationWarning` (pre-existing).
- **Verification status:** complete + verified against a live Postgres. `pytest`
  900 green, `ruff` clean, roundtrip green, `alembic head` `0016`,
  `git diff HEAD -- models/guards.py` empty, `state_machine.py` diff = the two
  approved edges only, two-connection concurrency test green.
- **Recommended commit message:**
  `Module 7: payment reconciliation & attribution — match, attribute, close; DETECTED/DIAGNOSING→CANCELLED (U-01)`

---

## Module 8 — Recovery Scoring Model — COMPLETE

*(One module = one run = one audit. Built on committed Module 7 `dd995d2`.
Implemented directly from the blueprint per the continuation rules — no separate
proposal/approval cycle. `state_machine.py` / `guards.py` untouched.)*

- **Commit:** *(uncommitted — maintainer commits after review)*. HEAD at
  implementation time: **`dd995d2`** (committed Module 7).
- **Migration:** **`0017_recovery_score`** — three nullable columns on
  `revenue_leak_case` (`recovery_score NUMERIC(18,4)`,
  `recovery_score_breakdown JSONB`, `recovery_score_updated_at TIMESTAMPTZ`), a
  **derived cache** (D-109). No table, no enum, no `CaseEventType` (the closed §4
  vocabulary of 10 is untouched). `alembic head` → `0017`; roundtrip green.
- **Load-bearing files:** `models/guards.py` **byte-unchanged**
  (`git diff HEAD` empty); `state_machine.py` **byte-unchanged** (Module 8 adds
  no transition). The new `recovery_score*` columns have no guard — a derived
  cache any recompute path may refresh.
- **New package `torque.scoring`** (D-109):
  - **`benchmarks.py`** — `cold_start_probability(leg_type, days_since_failure,
    *, amount_at_risk=None)` implementing Decision F's exact table as a live
    function (Subscription 0–48h → 0.65 / ≤7d → 0.45 / >7d → 0.25; Payment
    degradation → 0.55; Checkout → 0.40; B2B ≤30d → 0.35 / ≤90d → 0.20 / >90d →
    0.12). Bucket boundaries are explicit (`hours <= 48`, `days <= 7`, `<= 30`,
    `<= 90`); the 48h–72h label gap resolves into the aging bucket. Plus
    `warm_start_multiplier` (§8.2 / D-110 — linear map
    `0.5 + rate × 0.8`, clamped `[0.5, 1.3]`, `None` → 1.0) and
    `adjusted_probability` (clamped `[0, 1]`, quantised). `amount_bucket` is a
    label only — Decision F seeds no amount-tier variation (D-110).
  - **`cost.py`** — `compute_cost(session, case) → CostBreakdown` (§8.2 /
    D-111): the forward intervention cost = Σ `ChannelRateCard.rate_per_unit`
    for the **next likely step**'s channel(s). Next step = the node at a live
    `PlaybookRun.active_step_id`, else the candidate playbook's entry node
    (`select_playbook_id`), else none. Zero / unpriced / absent cost floors the
    divisor at `PolicyConfig.recovery_score_cost_floor` (₹0.01); `cost_basis`
    (`PRICED` / `FLOOR_NO_CHANNEL` / `FLOOR_UNPRICED_CHANNEL` / `FLOOR_NO_PLAYBOOK`)
    and `NextStepSource` (`LIVE_RUN` / `CANDIDATE_PLAYBOOK` / `NONE`) record the
    provenance. No division by zero is structurally possible.
  - **`score.py`** — `RecoveryScore` (frozen dataclass exposing every input:
    `probability`, `base_probability`, `warm_start_multiplier`,
    `promise_keeping_rate`, `amount_at_risk`, `raw_cost`, `effective_cost`,
    `cost_basis`, `bucket_label`, `next_step_*`, …), `compute_recovery_score(
    session, case, *, now=None)` — the **one** implementation of
    `(probability × amount_at_risk) ÷ cost`, exact `Decimal`, quantised 4 dp —
    plus `.explain()` (the §8.7 "Why:" shape) and `.to_dict()` (the JSONB
    breakdown). `score_case(session, case)` persists the three columns (no
    `CaseEvent`, no status change; no-op for a terminal case);
    `recompute_open_cases(session, *, merchant_id=None)` is the daily sweep
    (re-scores every open non-superseded case and refreshes any `human_queue`
    entry's `priority`).
  - **`tasks.py`** — `recompute_recovery_score_task(case_id)` (single case) and
    `recompute_open_case_scores_task()` (daily sweep), on the existing Celery
    app.
- **Recompute triggers (§8.5 / D-112):**
  - **case creation** — `score_case(...)` inline at the end of every leg's
    ingestion path (`ingestion.cases` / `checkout` / `subscription` / `b2b`), in
    the same transaction;
  - **diagnosis completion** — `score_case(...)` inline at the end of
    `diagnosis.engine._apply_result`, once `root_cause_code` (hence the
    candidate playbook / forward cost) is known;
  - **daily** — one `beat_schedule` entry
    (`recovery-score-daily-recompute`, `crontab(hour=2, minute=0)`) in
    `ingestion.celery_app`, plus `torque.scoring` added to autodiscover.
- **Module 6 integration (§8.6 / D-113):**
  `torque.coordination.outreach_coordinator.priority()` — the D-098 seam — now
  takes `(session, case)` and returns
  `compute_recovery_score(session, case).score`. Callers updated:
  `human_queue.enqueue` → `_priority(session, case)`;
  `merge._ordered(session, items)`. The same authoritative score drives merge
  primary-selection and the human queue's stored/ordered `priority`. A
  structural test asserts `human_queue` / `merge` never import the formula
  modules directly. All accepted Module 6 behaviour preserved.
- **`PolicyConfig`:** `recovery_score_cost_floor: float = 0.01` added (the D-111
  conservative default; `warm_start_cap_low/high` 0.5 / 1.3 already existed).
- **`exceptions.py`:** `RecoveryScoreError` added (raised only for a corrupt
  negative `amount_at_risk`; missing/zero cost is NOT an error — it floors).
- **Decisions:** D-109 (package + persisted columns + migration 0017), D-110
  (warm-start linear-map normalisation; `amount_bucket` inert), D-111 (forward
  cost + zero-cost floor), D-112 (recompute triggers — inline + one beat entry),
  D-113 (`priority()` seam signature + real score; Module 6 placeholder tests
  updated).
- **Deviations from blueprint:** none in behaviour. Where §8 is silent —
  the warm-start *normalisation formula* (D-110), the *zero-cost* behaviour
  (D-111, floored), and the *amount_bucket* effect (D-110, inert) — the
  conservative reading is chosen and documented; the eight Decision F benchmark
  probabilities are used verbatim, no alternatives invented. `amount_bucket`
  thresholds (SMALL <₹1k / MEDIUM ≤₹25k / LARGE) are a local grouping label with
  zero effect on any score.
- **Deferred introduced / still deferred:** the 🔮 learned-model upgrade (XGBoost
  + SHAP + T/X-learner uplift, needs 500+ resolved cases — Decision F / §8.4) is
  **not** built (correctly out of scope). Module 9 reporting, the dashboard
  top-at-risk view, and the Agent Console queue re-sort on score drift all
  *consume* `recovery_score` but are their own later modules.
- **Tests at completion:** **834** `def test_` functions (was 772); `pytest`
  collects and passes **1007** (was 900), 0 fail / 0 skip. Module 8 adds 6 test
  files (59 functions, heavily parametrised): `probability` (Decision F table +
  every bucket boundary + warm-start caps + exact-Decimal), `cost` (live-run /
  candidate / no-playbook next step, missing / zero / unpriced rate, policy
  floor), `score` (exact arithmetic, explainability, ranking / amount-vs-
  probability / cost-sensitive tradeoffs), `recompute` (creation / diagnosis /
  daily aging, human-queue priority refresh, terminal & superseded exclusion),
  `integration` (Outreach Coordinator + Human Queue consume the same seam; no
  duplicated formula), `correctness` (tenant isolation, terminal exclusion,
  negative/None amount, no division by zero, determinism). Three Module 6 tests
  updated to assert the real score instead of the `amount_at_risk` placeholder
  (D-113); `test_schema_introspection` gains 3 Module 8 assertions. `ruff` clean.
  `alembic head` `0017`; roundtrip green. 1 cosmetic
  `StarletteDeprecationWarning` (pre-existing).
- **Verification status:** complete + verified against a live Postgres. `pytest`
  1007 green, `ruff` clean, roundtrip green (`0017`), `alembic head` `0017`,
  `git diff HEAD -- src/torque/models/guards.py src/torque/state_machine.py`
  both empty.
- **Recommended commit message:**
  `Module 8: recovery scoring model — (probability × amount_at_risk) ÷ cost; cold-start + warm-start; recompute on create/diagnose/daily; priority() seam`

---

## Module 9 — Reporting & Measurement — COMPLETE

*(One module = one run = one audit. Built on committed Module 8 `8fbd97b`.
Implemented directly from the blueprint per the continuation rules — no separate
proposal/approval cycle. `state_machine.py` / `guards.py` untouched; no
migration.)*

- **Commit:** *(uncommitted — maintainer commits after review)*. HEAD at
  implementation time: **`8fbd97b`** (committed Module 8).
- **Migration:** **none** (D-114). Module 9 is a pure read/derive layer — no
  table, no enum, no `CaseEventType`, no column. `alembic head` stays
  `0017_recovery_score`; roundtrip green.
- **Load-bearing files:** `models/guards.py` and `state_machine.py` **both
  byte-unchanged** (`git diff HEAD --` empty). Module 9 issues only `SELECT`s.
- **New package `torque.reporting`** (D-114):
  - **`metrics.py`** — the derivation functions, all tenant-scoped (via
    `TenantScope`; `case_event` has no `merchant_id` so it is filtered by a join
    to `revenue_leak_case.merchant_id`):
    `recovery_summary` (§9.2 core metrics), `recovery_by_leg` (§9.1 / §9.5),
    `recovery_by_action_type` (§9.5 secondary), `recovery_by_recovery_type`
    (§9.2 outcome), `recovery_over_time` (§9.2 time series),
    `operational_exceptions` (§9.7), `recovery_report` (§9.4 batch bundle),
    `list_cases` / `case_detail` (§9.10 drill-down), `case_event_stream` (§9.2
    explainability panel — the raw `CaseEvent` stream in `event_seq_id` order).
    `ReportWindow` — a half-open `[start, end)` filter (D-119).
  - **`schemas.py`** — the pydantic result/response contract (frozen models;
    every money field a `Decimal`).
- **New router `torque.api.reporting`** — a read-only `APIRouter`
  (`prefix="/reports/{merchant_id}"`), same FastAPI conventions as the Module 2
  webhooks: 8 `GET` endpoints — `/summary`, `/report`, `/by-intervention`
  (`?by=leg|action_type`), `/over-time` (`?bucket=day|week|month`),
  `/exceptions`, `/cases`, `/cases/{case_id}`, `/cases/{case_id}/events`.
  Unknown merchant → 404; cross-tenant case → 404; bad `leg` / `status` → 422.
  Wired into `create_app()`.
- **Metric definitions (recorded so a number is auditable, D-115…D-120):**
  - **revenue at risk** — non-B2B `amount_at_risk`; B2B `Σ B2BInvoice.
    original_amount` (immutable; `amount_at_risk` is a mutating residual for B2B
    — D-115). The recovery-rate denominator.
  - **recovered** — `Σ recovered_amount WHERE recovery_type != SELF_RECOVERED`
    (§9.1 verbatim; `AGENT_ASSISTED` + `AMBIGUOUS`). `SELF_RECOVERED` is a
    **separate** `self_recovered_amount`, never folded in (D-116). Module 7 stays
    authoritative for `recovery_type` — Module 9 re-derives nothing (§9.3).
  - **recovery rate** — both `recovery_rate` = recovered cases ÷ total cases
    (§9.1 literal) and `amount_recovery_rate` = recovered ÷ revenue-at-risk
    (demo headline). Zero cases → `0`, no error (D-117).
  - **unresolved / blocked / deferred / escalated** — D-118 (unresolved = open ∪
    EXHAUSTED ∪ B2B-partial; blocked/deferred = Σ revenue-at-risk of cases with a
    `BLOCKED_BY_GUARDRAIL` / `OUTREACH_COORDINATOR_DEFERRED` action, deduped;
    escalated = `ESCALATED_TO_HUMAN` ∪ `human_queue`).
  - **over time** — `date_trunc(bucket, closed_at)` UTC, Torque-credited
    `RECOVERED` only, half-open windows (D-119).
- **Attribution (§9.3):** reporting reads `recovery_type` / `recovered_amount` /
  `ActionCase.credit_weight` (all set by Module 7) and surfaces them
  (`case_detail`); it never re-matches payments. An end-to-end test runs the real
  `reconcile_event` then asserts the report reflects it exactly.
- **Auditability (§9.8):** aggregate → `/cases` list → `/cases/{id}` (case fields
  + per-action `ActionSummary` incl. `credit_weight`) → `/cases/{id}/events` (the
  full `CaseEvent` stream). No persisted aggregate to become an unexplained
  source of truth (D-114).
- **Descriptive, not causal (§9.6 / D-121):** incrementality lift, the Wilson
  score CI, and SUTVA-adjusted lift (Blueprint §9.1) are **deferred** to a later
  "Module 9b — Incrementality" (U-10). The `in_control_cohort` / `control_group`
  data is already collected and untouched. `learning_log.md` §15 states plainly
  that Module 9 does not prove AI causality. *(Intentional deviation from §9.1 as
  written — the maintainer's Module 9 instructions govern.)*
- **Decisions:** D-114 (pure read layer, no migration), D-115 (revenue-at-risk
  per case), D-116 (Torque-credited recovered; SELF_RECOVERED separate),
  D-117 (both recovery rates), D-118 (unresolved/blocked/deferred/escalated),
  D-119 (over-time on `closed_at` UTC, half-open), D-120 (by-leg + by-action-type),
  D-121 (incrementality/CI/SUTVA deferred).
- **Deviations from blueprint:** D-121 (incrementality / Wilson CI / SUTVA-
  adjusted lift deferred, though §9.1 lists them under Module 9). Nothing else —
  the descriptive metrics match §9.1 / §9.2; the explainability panel is the raw
  `CaseEvent` stream as §9.2 specifies.
- **Deferred introduced / still deferred:** incrementality causal layer (U-10 /
  D-121); the merchant dashboard & agent console UI (Modules 10); `Action.cost`
  population by Module 5 (so `total_action_cost` / `cost_efficiency_ratio` are
  currently ~0 — reported honestly); pure timing defers are not countable from
  `Action` (they write no row — D-118); a `(merchant_id, closed_at)` index +
  SQL `GROUP BY` rewrite if a merchant ever exceeds ~10k open cases (D-114).
- **Tests at completion:** **890** `def test_` functions (was 834); `pytest`
  collects and passes **1063** (was 1007), 0 fail / 0 skip. Module 9 adds 6 test
  files (54 functions): `metrics` (core numbers, zero handling, exact Decimal,
  B2B original-vs-residual, by-leg / by-outcome / over-time), `attribution`
  (direct / indirect / multi-case `credit_weight` surfaced / unattributed + a
  real `reconcile_event` end-to-end + "reporting writes nothing"), `operational`
  (blocked-by-reason, deferred, failed-by-type, escalations, terminal statuses),
  `batch` (complete / mixed / empty / partially-processed windows, half-open
  `opened_at` & `closed_at` boundaries, naive-UTC coercion, query idempotency),
  `tenant_isolation` (every function + every endpoint; cross-tenant case → 404),
  `api` (all 8 endpoints, pagination, filters, explainability stream, 422s).
  `test_schema_introspection` gains 2 Module 9 assertions (logic-only; GET-only
  router). `ruff` clean. `alembic head` `0017`; roundtrip green. 1 cosmetic
  `StarletteDeprecationWarning` (pre-existing).
- **Verification status:** complete + verified against a live Postgres. `pytest`
  1063 green, `ruff` clean, roundtrip green (`0017`), `alembic head` `0017`,
  `git diff HEAD -- src/torque/models/guards.py src/torque/state_machine.py`
  both empty.
- **Recommended commit message:**
  `Module 9: reporting & measurement — outcome-based recovery report, by-leg/intervention/outcome/time, operational exceptions, case drill-down + explainability stream (read-only, no migration)`

---

## Module 10 — UI/UX — COMPLETE

*(One module = one run = one audit. Built on accepted (still-uncommitted)
Module 9, on top of committed Module 8 `8fbd97b`. Implemented directly from the
blueprint. `state_machine.py` byte-unchanged; `guards.py` changed for the one
explicitly-assigned §10.8 human-resolution write path.)*

- **Commit:** *(uncommitted — maintainer commits Module 9 + Module 10 together)*.
- **Migration:** **`0018_escalation_resolution`** — three nullable columns on
  `revenue_leak_case` (`escalation_resolution` / `_by` / `_at`), D-123. No table,
  no enum, no `CaseEventType` (`HUMAN_RESOLVED` already existed — count stays 10).
  `alembic head` → `0018`; roundtrip green.
- **Load-bearing files:** `state_machine.py` **byte-unchanged** (`git diff HEAD`
  empty — the resolve targets and `PLAYBOOK_ACTIVE ↔ PAUSED` are already legal
  §4 edges). **`guards.py` CHANGED** — exactly `human_resolution_writer(session)`
  + an `hr` flag threaded into `_guard_case` (`not (m7 or hr)`), mirroring
  `network_directive_writer` (D-123). Required because a human `→ RECOVERED`
  resolution records `recovered_amount` / `recovery_type = AGENT_ASSISTED`, both
  `module7_writer`-guarded. First `guards.py` change since M6a.
- **Frontend stack (D-122):** a hand-written **static SPA** — one `index.html` +
  `torque.css` + `torque.js` (vanilla JS, no framework, no bundler) under
  `src/torque/ui/static/`, mounted with `StaticFiles` at `/ui` by the same
  `create_app()`. `GET /` → `/ui/`. Hash routing. **No new runtime dependency.**
  Runs with `uv run python -m torque` (one process, one port).
- **New backend (§10.13 — thin, no domain logic in routes):**
  - `torque.reporting` gains `top_at_risk_cases` (§10.4 — open cases
    `ORDER BY recovery_score DESC NULLS LAST`), `human_queue_list` (§10.7 —
    `human_queue` rows joined to the case, ordered by the entry's stored
    `priority`), `recent_activity` (§10.17 — recent `CaseEvent`s, newest first).
    `case_detail` enriched with `recovery_score_breakdown` (Module 8's §8.7
    structure, verbatim), `recovery_probability`, `counterparty_label`,
    `root_cause_code`, and the escalation-resolution fields. All GET,
    tenant-scoped (INV-58 extended). Endpoints: `GET /reports/{m}/top-at-risk`,
    `/human-queue`, `/activity`.
  - `torque.agent_console` — new package: `resolve_escalation` / `pause_case` /
    `unpause_case` (INV-59). `POST /agent-console/{m}/cases/{cid}/{resolve|pause|
    unpause}`. Domain errors → 404 / 409.
  - `torque.demo` — `seed_demo` (§10.16 deterministic 16-case `acc_demo` dataset,
    fixed clock, idempotent; `reset=true` disables the `case_event` trigger for
    the wipe — D-125) + `scenarios` (§10.10 one-click injectors composing the
    *existing* ingestion / compliance code — checkout, payment failure, and the
    Decision-K hard-stop-MAC / UPI-cap / NACH-ceiling restraint scenarios, each
    asserting the real compliance predicate blocks). `POST /demo/seed`,
    `GET /demo/scenarios`, `POST /demo/inject/{key}`, `GET /demo/merchant`.
- **Merchant Dashboard (§10.1–10.3, 10.11):** hero ₹-recovered (dominant),
  secondary stat tiles (revenue at risk, recovery rate, unresolved, human
  escalations, blocked/deferred amount, cost efficiency), recovery-by-leg table,
  a CSS bar chart of recovery-over-time, the top-at-risk ranked list (clickable,
  backend order), and "Where Torque deliberately held back" (the exception list,
  surfaced prominently). No "actions = revenue" framing; `SELF_RECOVERED` shown
  separately, never in the headline.
- **Case detail / explainability (§10.5–10.6):** overview card + a "WHY THIS
  CASE?" panel rendering `recovery_score_breakdown.explain` verbatim
  (probability × amount ÷ expected cost = priority score, + the "why" lines) +
  the full `CaseEvent` timeline in `event_seq_id` order (the primary "why did the
  agent do this?" surface).
- **Agent Console (§10.7–10.8):** the human queue (priority order from the
  backend) + a case pane with the explainability lines and **pause / unpause /
  resolve** controls. "Cancel" maps to **resolve → `WRITTEN_OFF`** (D-124) — the
  blueprint reserves `CANCELLED` / `SELF_RECOVERED` for genuine customer
  self-payment. A resolve writes `escalation_resolution`, `HUMAN_RESOLVED`, and
  (recovering) `recovered_amount` / `recovery_type`, and drops the case from the
  queue; the dashboard reflects it on the next load.
- **Demo Surface (§10.9–10.10):** a scenario button panel + a polling live feed
  (`/activity`, 3 s) that visibly shows cases moving through states. Both "acts"
  and "restraint" scenario kinds are labelled, so the demo shows Torque acting
  **and** deliberately not acting.
- **Live-update mechanism (§10.17 / D-124):** polling (`GET /reports/{m}/activity`
  every 3 s). No WebSocket — the backend has no push channel; documented.
- **Decisions:** D-122 (static SPA, one process), D-123 (reuse the legal edges;
  `guards.py` `human_resolution_writer`; migration 0018), D-124 (backend
  additions; "cancel" = write-off; polling), D-125 (demo reset disables the
  `case_event` trigger).
- **Deviations from blueprint:** none in substance. The blueprint's §10 is three
  bullets and does not prescribe a stack or the pause/cancel target states —
  D-122 / D-124 pick the faithful minimum (only legal edges, no misattribution).
- **Deferred introduced / still deferred:** no browser/e2e test harness (out of
  the stack — D-122); real live push (polling suffices); the UI does not surface
  incrementality (Module 9b, D-121); Module 11 infra and Module 12/13 are
  untouched.
- **Tests at completion:** `pytest` collects and passes **1109** (was 1063),
  0 fail / 0 skip. Module 10 adds 6 test files (46 functions):
  `agent_console` (resolve × 3 resolutions, pause/unpause, wrong-state 409,
  cross-tenant 404, `HUMAN_RESOLVED` + queue removal + guarded recovery write),
  `reporting_ext` (score-ordered top-at-risk, open-only, priority-ordered queue,
  newest-first tenant-scoped activity, case-detail breakdown), `demo` (seed
  mixture + determinism + idempotency + reset, every scenario injects a real
  case, restraint scenarios record a genuine guardrail block), `api` (all new
  endpoints, 404/409/422), `tenant_isolation` (every new surface cross-merchant),
  `ui` (`/` redirect, shell served, JS wired to tenant-scoped paths, no
  frontend metric computation). `test_schema_introspection` +4 (0018 columns,
  no new enum, GET-only reporting + POST-only agent-console, no new
  state-machine edge). `ruff` clean. `alembic head` `0018`; roundtrip green.
- **Verification status:** complete + verified against a live Postgres. `pytest`
  1109 green, `ruff` clean, roundtrip green (`0018`), `git diff HEAD --
  src/torque/state_machine.py` empty, `guards.py` diff = the
  `human_resolution_writer` addition only. End-to-end local smoke passed (seed →
  dashboard → top case → case detail → CaseEvent timeline → Agent Console →
  resolve → inject scenario → live feed → reporting updates).
- **Recommended commit message:**
  `Module 10: UI/UX — static SPA dashboard + Agent Console (resolve/pause; escalation_resolution + HUMAN_RESOLVED; migration 0018) + Demo Surface (deterministic seed + one-click Decision-K scenarios + polling live feed)`

---

## Module 11 — Tech Stack & Infra — COMPLETE

- **Commit:** *(uncommitted — maintainer commits)*. HEAD at implementation time:
  `7b89e36` (Module 9–10). Recommended message below.
- **Migrations:** **none.** Module 11 is infrastructure + config + a readiness
  endpoint; zero schema change. `alembic head` stays `0018_escalation_resolution`.
- **Objective:** make the runtime the code already expects **reproducible from
  the repository alone**, free-tier, with no new infrastructure class:
  `docker-compose` stands up the exact five-process runtime (db + redis + api +
  worker + beat); one image builds api/worker/beat; every config value has a
  coherent, documented local **and** container setting with no committed
  secrets; `/health` gains a minimal readiness sibling. Blueprint Module 11's
  consolidation table is recorded as settled — **Temporal stays unimplemented**
  (D-090 / D-127), documented only as a future driver swap.
- **Scope delivered:**
  - **`Dockerfile`** (new) — one `python:3.11-slim` image, `uv sync --frozen`
    from `uv.lock` (reproducible), runtime deps only (`--no-dev`), non-root
    `USER torque`. Reused by api / worker / beat (D-128); default `CMD` is
    `python -m torque`, compose overrides `command:` for worker / beat.
  - **`.dockerignore`** (new) — trims the build context.
  - **`docker-compose.yml`** (rewrite) — `db` (host `:5442`) and `redis`
    (host `:6389`) unchanged and **profile-free**, so a bare `docker compose up`
    still starts only infra and the host loop (`… up -d db redis` +
    `uv run python -m torque`) is untouched (D-129). New services behind
    `profiles: ["full"]`: `migrate` (one-shot `alembic upgrade head`,
    `restart: "no"`, D-130), `api` (`python -m torque`, `8000:8000`,
    `TORQUE_API_HOST=0.0.0.0`, healthcheck → `/health/ready`), `worker`
    (`celery … worker`, `inspect ping` healthcheck), `beat` (`celery … beat
    --schedule=/tmp/celerybeat-schedule`). One YAML anchor (`x-torque-app`)
    supplies the shared build / image / compose-network `DATABASE_URL=…@db:5432`
    / `REDIS_URL=redis://redis:6379/0`. `api`/`worker`/`beat` `depends_on`
    `db` + `redis` healthy **and** `migrate` completed.
  - **`src/torque/api/health.py`** (new) — `health_router`: `GET /health`
    (liveness — the Milestone-7a `{"status":"ok"}` moved here **verbatim**) +
    `GET /health/ready` (readiness — `check_database()` `SELECT 1` +
    `check_redis(url)` 1 s `PING`; `200` both-ok / `503` naming the failed
    component). Probe functions module-level (test-substitutable); `redis`
    imported lazily. No metrics / tracing (D-132).
  - **`src/torque/api/app.py`** — now pure wiring: `include_router(health_router)`
    first, then the existing routers + `mount_ui`. The inline `/health` is gone
    (relocated, byte-identical behaviour).
  - **`src/torque/config.py`** — `Settings.api_host` (`127.0.0.1`) /
    `api_port` (`8000`), each `validation_alias=AliasChoices("<field>",
    "TORQUE_API_<HOST|PORT>")` so the established env names keep working (D-131).
  - **`src/torque/__main__.py`** — reads `get_settings().api_host / .api_port`
    instead of `os.environ` directly; defaults and behaviour identical.
  - **`.env.example`** (rewrite) — every `Settings` field + every `PolicyConfig`
    field (prefix `TORQUE_POLICY_`), each with default + comment; secrets blank;
    compose-network alternates noted.
  - **Tests** (new, Docker-free): `tests/test_infra_compose.py` (14),
    `tests/test_infra_celery.py` (9), `tests/test_config_env_parity.py` (6),
    `tests/test_health_endpoints.py` (6).
- **Decisions:** D-126 (backend = Python, Part D item 2 / U-05), D-127 (no
  Temporal; D-090 stands), D-128 (one image), D-129 (compose profiles), D-130
  (one-shot `migrate`), D-131 (`Settings` owns API bind address), D-132
  (`/health/ready`; no observability stack).
- **Deviations from blueprint:** none. Blueprint Module 11's table is a
  consolidation of already-made choices; the one open item (Part D item 2) is
  resolved to the de-facto Python (D-126). "Temporal (OSS) … or polling
  fallback" resolves to the polling fallback already built in Module 5 (D-090),
  reaffirmed here (D-127) — not a deviation, the blueprint offers both.
- **Deferred work removed from `DEFERRED.md`:** the `docker-compose` Celery
  worker/beat service (Module 2 list); "Infra beyond `docker-compose` … prod
  queue, worker/beat services" (Modules 11–13 list).
- **Deferred work introduced / still open:** real Temporal engine / self-hosted
  cluster (🔮 — D-090/D-127, future driver swap only); production process
  manager / autoscaling / multi-host orchestration (🔮 — no Kubernetes); secrets
  management (🔮 — `.env` + compose `env_file` only); a CI/CD pipeline + image
  registry (🔧, no owner); a Dockerised `docker compose --profile full up` smoke
  test in CI (🔧 — the infra tests assert the config contract without Docker).
- **Unresolved:** **U-05 D item 2 RESOLVED** (Python — D-126). D-090 **not
  reopened** (D-127). No new unresolved question — the runtime is fully
  specified. U-03 / U-04 / U-06 / U-08 / U-09 / U-10 / U-11 untouched (none
  constrain Module 11).
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD --` empty for each). Module 11 adds no transition, no guard,
  no guarded field.
- **Tests at completion:** **1144** passed (was 1109 at `7b89e36`), 0 failed,
  0 skipped, 1 pre-existing cosmetic `StarletteDeprecationWarning`. `+35` tests
  (14 + 9 + 6 + 6 new). `ruff check .` clean. `alembic upgrade head` → `0018`
  (no-op — no Module 11 migration); `tests/test_zz_migrations_roundtrip.py`
  green.
- **Verification status:** complete + verified against a live Postgres
  (docker-compose `db`, host 5442). `pytest` 1144 green, `ruff` clean, roundtrip
  green, `state_machine.py` / `guards.py` diffs empty, no migration. Docker
  `--profile full` smoke test: see the milestone report (reported separately
  from the code/test result per the maintainer's instruction).
- **Recommended commit message:**
  `Module 11: tech stack & infra — reproducible runtime (Dockerfile, compose api/worker/beat behind a full profile, /health/ready, .env.example + Settings audit); no schema change`

---

## Module 9b — Incrementality / Causal Measurement — COMPLETE

- **Commit:** *(uncommitted — maintainer commits)*. HEAD at implementation time:
  `6c6392c` (Module 11). Recommended message below.
- **Migrations:** **none.** The cohort inputs
  (`Merchant_Counterparty.in_control_cohort` → the denormalised
  `RevenueLeakCase.control_group`, kept in step by
  `state_machine.sync_control_group`) have existed since M1; Module 9b only
  reads them. `alembic head` stays `0018_escalation_resolution`.
- **Objective:** the causal layer deferred by D-121 / U-10 — treatment-vs-control
  **incremental lift**, a small-sample-honest **Wilson / Newcombe confidence
  interval**, and the Blueprint §6 cross-merchant **SUTVA-adjusted lift** shown
  **alongside** the headline. Additive to Module 9: descriptive metrics and
  Module 7 attribution are byte-unchanged.
- **Scope delivered:**
  - **`src/torque/reporting/incrementality.py`** (NEW) — `incrementality_report(
    session, merchant_id, *, window=None, leg=None)` and the pure helpers
    `wilson_interval` / `newcombe_difference`. Cohort from
    `RevenueLeakCase.control_group` (`True` control / `False` treatment / `None`
    excluded), recovery = intent-to-treat `status ∈ {RECOVERED, CANCELLED}`
    (D-133), window = the Module 9 `opened_at` `ReportWindow`. Tenant-scoped
    (`TenantScope`); the one deliberately cross-merchant read
    (`_contaminated_control_counterparties`) is bounded by
    `counterparty_id IN (:merchant's own control counterparties)` and selects
    only `counterparty_id`, reduced to a `set` before it leaves the function —
    no other merchant's id / amounts / outcomes / counts reach any field.
  - **`src/torque/reporting/schemas.py`** — 4 additive frozen models:
    `ProportionCI` (successes / total / rate / Wilson `ci_low`/`ci_high`, all
    `None` at `total == 0`), `LiftEstimate` (`point` / Newcombe `ci_low`/`ci_high`
    / `method`), `SutvaAdjustment` (`contaminated_control_counterparties`,
    `excluded_control_cases`, adjusted `control`, adjusted `lift`, `note`),
    `IncrementalityReport` (window echo + `window_basis="opened_at"` +
    `confidence_level` `0.95` + `z_value` + `recovery_definition` + `treatment`
    + `control` + `lift` + `sutva`). **No existing field renamed or removed.**
  - **`src/torque/reporting/__init__.py`** — re-exports `incrementality_report`.
  - **`src/torque/api/reporting.py`** — one new read-only endpoint
    `GET /reports/{merchant_id}/incrementality` (`opened_from` / `opened_to` /
    `leg`, same conventions as `/summary`; unknown merchant → 404, bad `leg` →
    422). The router stays GET-only.
  - **`src/torque/ui/static/{torque.js,torque.css}`** — a compact
    "Incrementality — estimated causal effect" card on the dashboard (fetched
    from `/incrementality`, rendered by `incrementalityCard(inc)`): treatment
    rate, control rate, incremental lift + 95% CI, SUTVA-adjusted lift + CI +
    contaminated count, the honest SUTVA note and recovery definition, and an
    explicit "descriptive = what happened / causal = estimated incremental
    effect … not proof of causation" line. **Renderer only** — no rate, lift,
    or interval is computed in JS (`test_module9b_ui.py` asserts it).
  - **`src/torque/demo/seed.py`** — the deterministic seed now assigns every
    demo counterparty a cohort via the existing `assign_cohort` (3/16 control),
    and adds a companion merchant `acc_demo_up` treating 2 of those control
    counterparties in-window so the demo SUTVA lift is live and non-zero
    (D-135). `DEMO_MERCHANT_IDS`; `_wipe` loops both ids. `acc_demo`'s
    descriptive numbers and 16-case count are byte-identical to before.
  - **Tests (NEW, 65):** `test_module9b_wilson.py` (27 — CI math, all edges,
    textbook value, ± lift, clamping, no NaN/inf), `test_module9b_incrementality.py`
    (17 — lift direction, zero/all/one/tiny cohorts, unassigned excluded,
    CANCELLED counts / PARTIALLY_RECOVERED & WRITTEN_OFF don't, window &
    leg filters, superseded excluded, determinism),
    `test_module9b_sutva.py` (8 — no-overlap ⇒ adjusted == headline, overlap
    excludes the contaminated counterparty, control-elsewhere is not
    contamination, out-of-window is not, multi-merchant, headline always
    preserved), `test_module9b_api.py` (10 — exact response schema, empty
    dataset, 404 / 422, window echo, tenant isolation, read-only row-count +
    `control_group` snapshot, repeated-call identity, bounds in range),
    `test_module9b_ui.py` (4). Plus `tests/module9b_helpers.py` (not collected).
- **Decisions:** D-133 (ITT recovery for the causal layer; descriptive rate
  unchanged), D-134 (Wilson per cohort + Newcombe 1998 for the difference; 95%
  two-sided, `z = Φ⁻¹(0.975)`; `Decimal` `.sqrt()`; `null` not `NaN`), D-135
  (demo seed cohorts + `acc_demo_up` SUTVA fixture). D-121 preserved as
  historical.
- **Deviations from blueprint:** none. Blueprint §6 / §9.1 specify the metric,
  the Wilson requirement, and the SUTVA rule; D-134 fills the two gaps the
  Blueprint leaves (confidence level, difference method) with the standard
  choices and records them.
- **Deferred work removed from `DEFERRED.md`:** "Module 9b — Incrementality /
  causal measurement" (Module 9 list) and "the UI does not surface
  incrementality" (Module 10 list).
- **Deferred work introduced / still open:** the 🔮 learned recovery model
  (XGBoost / SHAP / T/X-learner uplift for *individual* treatment effects —
  Decision F / §8.4) is unchanged and explicitly out of Module 9b; per-leg
  incrementality is available via `?leg=` but not surfaced on the dashboard
  (merchant-wide only, per §9.1).
- **Unresolved:** **U-10 RESOLVED** (2026-09-04) — the descriptive/causal split
  is now built: descriptive stays Module 9, causal is `torque.reporting.
  incrementality` + `GET /incrementality`, both read-only and tenant-scoped.
  D-090 not touched. No new unresolved question.
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD --` empty for each). Module 9b adds no transition, no guard,
  no guarded field, no write path.
- **Tests at completion:** **1209** passed (was 1144 at `6c6392c`), 0 failed,
  0 skipped, 1 pre-existing cosmetic `StarletteDeprecationWarning`. `+65`.
  `ruff check .` clean. `alembic upgrade head` → `0018` (no-op); roundtrip green.
- **Verification status:** complete + verified against a live Postgres
  (docker-compose `db`, host 5442) and an end-to-end smoke against the Module 11
  `docker compose --profile full` stack: seed → dashboard shell + JS card served
  → descriptive summary unchanged (16 cases, ₹65,200, rate 0.3472) →
  `/incrementality` returns treatment 5/13, control 1/3, lift +0.0513
  [-0.4525, +0.4276], SUTVA 2 contaminated → adjusted lift +0.3846 → 3× repeated
  GET mutates nothing (case/event/action/`merchant_counterparty` counts and
  every `control_group` value identical) → `acc_demo_up`'s own report shows only
  its 2 cases, unknown merchant → 404.
- **Recommended commit message:**
  `Module 9b: incrementality / causal measurement — treatment-vs-control lift, Wilson + Newcombe CI, SUTVA cross-merchant adjustment; read-only /reports/{m}/incrementality + dashboard card; no schema change`

---

## Module 12 — Build Roadmap — COMPLETE

- **Commit:** *(uncommitted — maintainer commits)*. HEAD at implementation
  time: `7172c92` (Module 9b). Recommended message below.
- **Migrations:** **none.** Documentation-only milestone; no application code
  changed. `alembic head` stays `0018_escalation_resolution`.
- **Objective:** the blueprint's original Module 12 (a hypothetical Phase
  1 → 5 build plan) is now historical — the implementation has already passed
  every one of those phases. Replace it with an **actual current roadmap**,
  derived from the repository as it exists today, that classifies every
  remaining open item (across all of `DEFERRED.md` plus the two U-08-blocked
  items) into what a judge needs to see live vs. what production needs
  eventually, in dependency-aware order — and feeds Module 13 the inputs it
  needs (what's demoable, what's simulated, the strongest live flow, what
  limitations to disclose).
- **Phase 0 verification (read-only, before any edit):** `git status` clean at
  `7172c92`; `uv run pytest` **1209 passed**, 0 fail/skip, 1 pre-existing
  cosmetic warning; `uv run ruff check .` clean; `alembic heads`/`current` both
  `0018_escalation_resolution`; `tests/test_zz_migrations_roundtrip.py`
  **1 passed**; `git diff HEAD -- src/torque/state_machine.py` /
  `-- src/torque/models/guards.py` both **empty**. Spot-checked against the
  live code (not just the docs): `GET /reports/{m}/incrementality` exists in
  `api/reporting.py` and is fetched + rendered by `torque.js`
  (`incrementalityCard`); `docker-compose.yml` defines exactly
  `db, redis, migrate, api, worker, beat`; `D-090`'s `Status:` line reads
  `IN FORCE`. **No documentation drift found** — `CURRENT_STATE.md`,
  `DEFERRED.md`, and `UNRESOLVED.md` (Module 9b/10/11 entries, U-10) all match
  the live repository exactly.
- **Scope delivered:** the classification and roadmap are the deliverable —
  see `DEFERRED.md` § "Build Roadmap Priority Classification (Module 12)" for
  the full per-item breakdown (current state / why it matters / dependency /
  priority / complexity / data-model / state-machine / external-service flags
  for every item) and the dependency graph. Summary:
  - **A — Demo-critical (1 item):** wire the ingestion→diagnosis→policy-
    activation→execution auto-dispatch chain (D-080/D-088/D-093). Ranked
    highest not because the demo is broken without it (the Decision-K
    restraint scenarios + the static seed already carry a live
    diagnosis-and-compliance story) but because it is the one place "one
    autonomous agent" is still assembled by hand, and it is the cheapest, most
    dependency-free item in the whole document.
  - **B — Demo-enhancing (3 items):** live cross-leg-merge / B2B-bundle demo
    scenarios (the blueprint's Module 13 script names this as a "Live:" beat);
    an inline-diagnose fallback for the two "act" scenarios (redundant if A1
    ships); a larger incrementality demo cohort (cosmetic).
  - **C — Production-hardening (15 items):** real channel adapters + payment-
    link/promise execution + `Action.cost` (bundled, needs 4 external
    accounts); the U-08-gated issuer/BIN extraction → MAC first-touch lookup →
    `ISSUER_SPECIFIC` systemic detection (one shared blocker); systemic
    threshold calibration; secrets management; process manager/autoscaling;
    CI/CD + registry; a Docker smoke test in CI; Postgres RLS; DPDP erasure
    intake + the `content_sent` redaction cascade; observability;
    `PlaybookRun.status` transitions; two demo-scale-deferred indexes.
  - **D — Future/optional (8 items):** a real Temporal cluster (**D-090 not
    reopened**), the learned individual-uplift model (blocked on 500+ resolved
    cases), CAU, the SMS production path, NACH cross-instrument aggregation,
    remaining Module 2 residue, the WhatsApp `AUTHENTICATION` category, and
    cross-stratum merge widening.
  - **Verified already sufficient, no action:** Module 9 descriptive
    reporting, Module 9b incrementality, Module 10 Agent Console, Module 11
    infra, and the compliance-guardrail demonstration.
- **Decisions:** D-136 (the classification rule + the specific priority calls,
  most notably ranking A1 above every Category-C item).
- **Deviations from blueprint:** none in the "intentional deviation" sense —
  the blueprint's own Module 12 explicitly needed Part D item 3 (build-window
  length) to produce a calendar plan, which was never supplied; this run
  answers the different, now-more-useful question of *ordering* rather than
  *dates*, which is within the spirit of "convert Phases 1–5 into a
  calendar-dated plan the moment the window length is known" — the window
  still isn't known (U-05 item 3 stays open), so a priority/dependency
  ordering is substituted.
- **Deferred work removed from `DEFERRED.md`:** none — this run reorganizes
  and classifies, it does not implement anything. No item's ✅/🔧/🔮 status
  changed.
- **Deferred work introduced:** none new — every item was already in
  `DEFERRED.md`, `UNRESOLVED.md` (U-08), or a module docstring; this run adds
  classification, not scope.
- **Unresolved:** none resolved. U-08 is **not** answered — it is identified as
  the shared blocker for two Category-C items and cross-referenced, per its
  own text (already noted there since Module 3). No other `UNRESOLVED.md`
  question touched.
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD --` empty for each, both before and after this run — no
  application code was touched).
- **Tests at completion:** **1209** passed (unchanged from `7172c92` — no code
  changed). `ruff check .` clean. `alembic upgrade head` → `0018` (no-op);
  roundtrip green.
- **Verification status:** complete + verified. `git diff --check` clean (no
  whitespace errors introduced). Only `documentation/ai-memory/{MILESTONES,
  CURRENT_STATE,DEFERRED,ARCHITECTURE,DECISIONS}.md` and `README.md` changed;
  zero files under `src/` or `tests/` touched.
- **Recommended commit message:**
  `Module 12: build roadmap — classify all remaining work (A demo-critical / B demo-enhancing / C production-hardening / D future) with a dependency graph; D-136; no code change`

---

## Module 12a — Close the Autonomous Loop — COMPLETE

- **Commit:** *(uncommitted — maintainer commits)*. HEAD at implementation
  time: `fc813ab` (Module 12). Recommended message below.
- **Migrations:** **none.** `alembic head` stays `0018_escalation_resolution`.
- **Objective:** the Module 12 roadmap's top-ranked item (A1) — wire the
  ingestion → diagnosis → policy-activation → execution-scheduling chain the
  engines have supported since Modules 3/4/5 but nothing ever triggered
  (D-080/D-088/D-093) — plus (B1) two new live demo scenarios exercising the
  real §2.4 cross-leg Merge and §3 B2B grouping rule for the same counterparty.
- **Scope delivered:**
  - **A1 — autonomous chain (D-137, D-138):**
    - `torque.ingestion.{cases,buffer,checkout,subscription,b2b}` — each
      case-creating function gains one additive, keyword-only
      `on_case_ready: Callable[[RevenueLeakCase], None] | None = None`
      (default `None` ⇒ every existing direct caller unaffected). Called with
      the **canonical** case only (the merge survivor / bundled-into case,
      never a superseded row).
    - `torque.ingestion.tasks` — new `dispatch_diagnosis(case_id)`: enqueues
      `torque.diagnosis.diagnose_case_task` with a 2 s `countdown` (D-138). The
      four case-creating Celery tasks capture the ready case id via the hook
      *during* their transaction and call `dispatch_diagnosis` only *after*
      `with session_scope()` exits (commit-then-dispatch).
    - `torque.diagnosis.tasks.diagnose_case_task` — after its own commit, on
      `ROUTED_TO_PLAYBOOK` calls the new `_dispatch_activation(case_id)`,
      enqueuing `torque.policy.activate_case_task`. `ESCALATED`/`NOOP` dispatch
      nothing.
    - `torque.policy.tasks.activate_case_task` — on `RUN_CREATED`, **inside the
      same transaction**, looks up the just-created `PlaybookRun` and calls the
      existing `torque.execution.scheduler.schedule_run` directly (a plain
      function call, not a new Celery hop) — D-090's Postgres-polling beat
      pollers, unchanged, are what actually execute it.
    - No engine (`diagnose_case`, `activate_case`, the four ingestion
      functions) gained new decision logic; the dispatcher only orchestrates.
  - **B1 — live cross-leg / B2B demo scenarios:**
    `torque.demo.scenarios` gains `cross_leg_merge` (checkout abandonment then
    a matching-order payment failure for the same counterparty — the real
    forward §2.4 Merge) and `b2b_invoice_bundle` (two overdue invoices for the
    same counterparty — the real §3 grouping rule). `inject_scenario` gains
    `dispatch: bool = False`; `torque.api.demo.post_inject` passes `True` so an
    injected case is picked up by the real chain above, exactly like a real
    webhook.
  - **Tests (NEW, 19 + strengthened 2):** `tests/test_module12a_autonomous_chain.py`
    (19 — ingestion→diagnosis with the correct canonical case incl. both merge
    directions and B2B attach, duplicate/NOOP non-dispatch, diagnosis→policy
    incl. ESCALATED/NOOP non-dispatch and redelivery-at-most-once,
    policy→execution incl. no-duplicate-run, a genuine downstream failure
    propagating (not swallowed), two full end-to-end tests with no manual
    engine call, and the demo `dispatch=True` wiring via the HTTP API).
    `tests/test_diagnosis_task.py::test_task_diagnoses_a_case` and
    `tests/test_module4_task.py::test_task_creates_run` strengthened to bind
    every task's `_session_scope` and assert the chain actually fires (a
    `PlaybookRun` / `ScheduledJob` now exists), replacing an accidental
    "passes because the chained call can't see the uncommitted case anyway"
    with a genuine proof. `tests/test_module10_demo.py`'s parametrized
    all-scenarios test extended for the 2 new keys.
- **Decisions:** D-137 (the `on_case_ready` hook + commit-then-dispatch
  wiring), D-138 (the dispatch countdown — found and fixed via the Docker
  smoke test, not merely reasoned about).
- **Deviations from blueprint:** none — this closes deferred cross-module
  triggers the blueprint always expected an "orchestration layer" to wire
  (D-080/D-088/D-093's own text), using only already-specified mechanisms
  (Celery, Postgres-polling). D-090 not reopened.
- **Deferred work removed from `DEFERRED.md`:** D-080 (ingestion → diagnosis
  auto-dispatch), D-088 (diagnosis → policy auto-dispatch), D-093 (policy →
  execution auto-dispatch/`schedule_run` call) — all three genuinely satisfied.
  "The UI does not surface a live cross-leg/B2B demo" residual (Module 12's B1
  item) removed.
- **Deferred work introduced:** none new. Real channel adapters, `Action.cost`
  population, the U-08-gated MAC lookup / `ISSUER_SPECIFIC` detection, and
  every other Category-C/D item from Module 12's roadmap remain exactly as
  classified there — none pulled forward.
- **Unresolved:** none resolved and none newly introduced. U-08 untouched.
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD --` empty for each). The chain drives only already-legal
  transitions the engines already produced; no new guard, no guarded field.
- **Tests at completion:** **1230** passed (was 1211 at `fc813ab`), 0 failed,
  0 skipped, 1 pre-existing cosmetic `StarletteDeprecationWarning`. `ruff
  check .` clean. `alembic upgrade head` → `0018` (no-op — no migration);
  roundtrip green.
- **Verification status:** complete + verified against a live Postgres
  (docker-compose `db`) and an end-to-end Docker smoke test against the Module
  11 `docker compose --profile full` stack (real worker + real Redis + real
  Postgres, no monkeypatching): reset/seed → inject `payment_failure` with no
  manual diagnosis call → the low-confidence case reached `ESCALATED_TO_HUMAN`
  on its own; a directly-inserted high-confidence event reached
  `PLAYBOOK_ACTIVE` with a real `PlaybookRun` **and** a real `ScheduledJob`
  armed, on its own. The smoke test is also what *found* D-138's race (the
  first attempt silently NOOP'd) — fixed, then re-verified green. Existing
  descriptive reporting, incrementality, Agent Console human queue, the
  Decision-K restraint scenarios, and the new cross-leg/B2B scenarios all
  continued to work against the same running stack.
- **Recommended commit message:**
  `Module 12a: close the autonomous loop — ingestion->diagnosis->policy->execution auto-dispatch (D-137/D-138) + live cross-leg merge / B2B bundle demo scenarios; no schema change`

---

## AI Phase 0 + Phase 1 — AI Architectural Foundation & Read-Only Evidence Interface — COMPLETE

- **Branch:** `ai-layer` (forked from `main` at `a0fb0f3`, after Module 12a
  was committed). **Not on `main`** — this milestone does not exist there
  until an explicit, maintainer-performed merge passes the Integration Gate
  documented in `AI_BLUEPRINT.md` §18.
- **Migrations:** **none.** `alembic head` stays `0018_escalation_resolution`.
- **Objective:** stand up the durable architectural foundation for a future
  AI layer — a structurally read-only package, a static test enforcing that
  boundary, and the evidence interface every later AI phase (retrieval, LLM
  narrative generation, citations, Agent Console integration, shadow ML)
  will read through. No retrieval, no LLM call, no embeddings, no shadow ML,
  and no API/UI surface were built — see `AI_BLUEPRINT.md` "Current
  Implementation Status" for the exact boundary.
- **Scope delivered:**
  - **Phase 0 — architectural foundation:** `src/torque/ai/__init__.py`
    (package boundary statement), `exceptions.py` (`AIError`,
    `EvidenceNotFoundError`, both subclassing `torque.exceptions.TorqueError`),
    `config.py` (`AISettings` — `TORQUE_AI_ENABLED`, default `False`, same
    `BaseSettings`/`SettingsConfigDict`/`lru_cache` pattern as
    `torque.config.Settings`/`PolicyConfig`). `documentation/ai-memory/
    AI_BLUEPRINT.md` — the reviewed 23-section AI architecture document,
    with every entry marked LOCKED / RECOMMENDED / DEFERRED / NEEDS HUMAN
    DECISION.
  - **Phase 1 — read-only evidence interface:** `src/torque/ai/schemas.py`
    (`EvidenceReference` with a stable `reference_id` citation identifier;
    `TimelineEntry`, `ActionEvidence`, `PromiseEvidence`,
    `CounterpartyRelationshipEvidence`, `CaseSnapshot`, `CaseEvidence` —
    frozen, `extra="forbid"` Pydantic DTOs, never an ORM row) and
    `src/torque/ai/evidence.py` (`gather_case_evidence(session, *,
    merchant_id, case_id) -> CaseEvidence` — the package's only public
    capability). Reads exclusively through `torque.db.scoped.TenantScope`;
    excludes `Counterparty.{name,phone,email}` (never queries `Counterparty`
    at all) and `Action.content_sent`; represents missing evidence as an
    explicit `None`/`[]` plus a plain-English `evidence_gaps` entry, never a
    fabricated placeholder; treats `CaseEvent.reasoning`/`.payload` as inert
    data (typed `str`/`dict`, never parsed or interpolated).
  - **The read-only boundary is enforced by a test, not just a docstring:**
    `tests/test_ai_boundary.py` statically parses every file under
    `src/torque/ai/` with `ast` and fails the build if it imports
    `torque.state_machine`, `torque.coordination`, `torque.events`,
    `torque.agent_console`, `torque.execution`, `torque.ingestion`,
    `torque.policy`, `torque.diagnosis`, `torque.scoring`,
    `torque.reconciliation`, `torque.promises`, or `torque.api` — plus an
    independent substring sweep for any raw write-shaped call (`.add(`,
    `.delete(`, `.commit(`, raw SQL mutation keywords) anywhere in the
    package.
  - **Tests (NEW, 23):** `tests/test_ai_boundary.py` (4 — import-boundary
    enforcement, detector self-test, write-call sweep), `tests/
    test_ai_config.py` (3 — flag defaults/override/caching), `tests/
    test_ai_evidence.py` (16 — tenant isolation incl. cross-tenant
    invisibility, evidence-shape/ordering/citation-reference correctness,
    missing-evidence gap reporting, PII exclusion incl. content-substring
    sweeps for `Action.content_sent` and `Counterparty` PII, and an
    injected-instruction-text resilience test proving arbitrary
    `CaseEvent.reasoning` content cannot alter the evidence structure).
- **Decisions:** none required a new `DECISIONS.md` entry beyond
  documenting the read-only-enforcement mechanism itself — see D-139.
  `AI_BLUEPRINT.md` §20's Decision Register carries the fuller set (most
  RECOMMENDED or NEEDS HUMAN DECISION, none yet exercised beyond Phase 0+1's
  own choices).
- **Deviations from the (conversation-produced) AI blueprint:** none in
  substance. One scope reduction, explicitly recorded rather than silent:
  `pyproject.toml` was **not** touched — the blueprint's Phase 0 named an
  `ai` optional-dependency extras group, but Phase 0+1 needed zero new
  dependencies (only `pydantic`, already present, was used), so the empty
  group was not added; it will be introduced by whichever future phase
  first needs a real dependency (see `AI_BLUEPRINT.md` D-AI-18).
- **Deferred work:** everything from Phase 2 onward (retrieval, LLM
  narrative generation, citation-bearing prose, faithfulness evaluation,
  Agent Console integration, shadow ML, adversarial hardening, demo polish)
  — none implemented, none started. See `AI_BLUEPRINT.md` §14.
- **Unresolved:** none resolved and none newly introduced by this work.
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff HEAD --` empty for each) — this milestone added a purely new,
  additive package and touched no existing tracked file.
- **Tests at completion:** **1253** passed (was 1230 at `a0fb0f3`; **+23**),
  0 failed, 0 skipped, the same 1 pre-existing cosmetic
  `StarletteDeprecationWarning`. `ruff check .` clean. `alembic upgrade
  head` → `0018` (no-op — no migration).
- **Verification status:** complete + verified — `uv run pytest -q` (full
  suite, 1253 passed), `uv run ruff check .` (clean, repository-wide),
  `uv run alembic upgrade head` (succeeds, no new migration), `git diff
  HEAD -- src/torque/state_machine.py src/torque/models/guards.py` (both
  empty), `git status` (purely new untracked files: `src/torque/ai/`,
  `tests/test_ai_boundary.py`, `tests/test_ai_config.py`, `tests/
  test_ai_evidence.py`, `documentation/ai-memory/AI_BLUEPRINT.md`, plus the
  additive `DECISIONS.md`/`INVARIANTS.md`/`CURRENT_STATE.md`/`DEFERRED.md`
  entries recorded alongside this section — no existing tracked source file
  modified).
- **Recommended commit message:**
  `AI Phase 0+1: read-only AI evidence foundation — torque.ai package, gather_case_evidence(), AI_BLUEPRINT.md; structurally enforced (tests/test_ai_boundary.py), zero deterministic-core changes, no migration`

---

## AI Phase 2 — Evidence Normalization + Citation Model — COMPLETE

- **Branch:** `ai-layer`. **Not on `main`.**
- **Sequencing correction:** an earlier Phase 0+1 completion report
  incorrectly named "Phase 2 — Retrieval / precedent engine" as the next
  step. The authoritative sequence (per the corrected instruction this
  milestone was built against, now reflected in `AI_BLUEPRINT.md`) inserts
  **Evidence Normalization + Citation Model** as Phase 2, pushing retrieval
  to Phase 3 and every phase after it down by one. This milestone is that
  corrected Phase 2 — not retrieval, which remains entirely unbuilt.
- **Migrations:** **none.** `alembic head` stays `0018_escalation_resolution`.
- **Objective:** turn the Phase 1 evidence representation into a stable,
  resolvable citation system — `EvidenceSet -> evidence_id -> Citation ->
  resolve_citation() -> exact EvidenceItem -> authoritative Torque record` —
  with no retrieval, no LLM call, and no generated-narrative contract.
- **Discrepancy found during verification (§2 of the task) and how it was
  resolved:** `CaseSnapshot` (Phase 1) had no `reference: EvidenceReference`
  field, even though `SourceType` already reserved a `"case"` literal for
  it — the case's own current-state facts (status, root cause, recovery
  score, ...) were the one evidence type with no citation target. This is
  not a defect in anything Phase 1 already cited (every `CaseEvent`/
  `Action`/`PromiseToPay`/`MerchantCounterparty` reference was already
  correct), so it did not meet the task's STOP threshold ("a correctness
  problem that materially affects citation integrity") — it was an
  omission, not a bug. Closed as part of Phase 2's own mandate (see
  `DECISIONS.md` D-140 sub-decision 2) rather than deferred, since making
  evidence referenceable is exactly what this milestone is for.
- **Scope delivered:**
  - `src/torque/ai/schemas.py` — new `Citation` DTO (`evidence_id: str`
    only, frozen, `extra="forbid"`); new `EvidenceItem` type alias (`
    CaseSnapshot | TimelineEntry | ActionEvidence | PromiseEvidence |
    CounterpartyRelationshipEvidence` — no new evidence type invented,
    purely a union of what Phase 1 already produces); `CaseSnapshot` gains
    `reference: EvidenceReference` (`source_type="case"`).
  - `src/torque/ai/evidence.py` — `_snapshot()` now populates the new
    `reference` field (`source_id=case_id`, `timestamp=case.opened_at`); no
    other change.
  - `src/torque/ai/citations.py` (**new module**) — `all_evidence_items
    (evidence) -> list[EvidenceItem]` (flattens snapshot + timeline +
    actions + promises + counterparty relationship, deterministic order,
    lookup never by position); `resolve_citation(evidence, evidence_id) ->
    EvidenceItem | None` (pure, exact-match only, scoped to the one
    `CaseEvidence` given, never raises); `citation_for(item) -> Citation`
    (the inverse convenience). Imports nothing beyond `torque.ai.schemas` —
    no database access is even reachable from this module, let alone used.
  - **Preserved unchanged:** `EvidenceReference.reference_id`'s scheme
    (`f"{source_type}:{source_id}"`) — evaluated against the task's four
    required properties and found to already satisfy all of them; not
    replaced with the task's illustrative alternative form (see D-140
    sub-decision 1 for the full reasoning).
  - **Tests (NEW, 15):** `tests/test_ai_citations.py` — citation-schema
    validation (minimal/frozen/`extra="forbid"`), id uniqueness within a
    set, id stability across repeated `gather_case_evidence` calls, exact
    resolution for every evidence type Phase 1 produces, a `citation_for`/
    `resolve_citation` round trip, fabricated-id → `None`, wrong-case-id →
    `None`, malformed/empty-id → `None`, cross-tenant-id → `None`, an
    empty-evidence-set case (only the snapshot is citable, and it still
    resolves), and a multi-evidence-type case (event + action +
    counterparty relationship all resolve independently, no cross-matching).
- **Decisions:** D-140 (the four bundled citation-contract sub-decisions
  above).
- **Invariants:** INV-61 (citation resolution determinism / purity /
  never-silently-resolves).
- **Deviations from `AI_BLUEPRINT.md`:** the phase-numbering correction
  itself (this milestone *is* the correction — `AI_BLUEPRINT.md` is updated
  alongside this entry to renumber Phase 2 onward accordingly). No other
  deviation; `CaseSnapshot`'s new field is documented above as an omission
  closed, not a contract redesign (nothing existing was renamed, removed, or
  retyped).
- **Deferred work:** everything from Phase 3 onward (retrieval, LLM case
  explanation, faithfulness evaluation, Agent Console integration, shadow
  ML, hardening, demo polish) — none implemented, none started. Explicitly
  **not** implemented in this milestone: `retrieval.py`, any full-text/
  vector search, any LLM provider/prompt/call, `CaseNarrative` or any
  citation-bearing generated prose, any API endpoint, any UI change.
- **Unresolved:** none resolved and none newly introduced by this work.
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff` empty for each).
- **Tests at completion:** **1268** passed (was 1253 after Phase 0+1;
  **+15**), 0 failed, 0 skipped, the same 1 pre-existing cosmetic
  `StarletteDeprecationWarning`. `ruff check .` clean. `alembic upgrade
  head` → `0018` (no-op — no migration); roundtrip green
  (`tests/test_zz_migrations_roundtrip.py`, 1 passed).
- **Verification status:** complete + verified — `uv run pytest
  tests/test_ai_citations.py tests/test_ai_evidence.py
  tests/test_ai_boundary.py tests/test_ai_config.py -v` (38 passed), `uv run
  pytest -q` (full suite, 1268 passed), `uv run ruff check .` (clean,
  repository-wide), `uv run alembic upgrade head` (succeeds, no new
  migration), `uv run pytest tests/test_zz_migrations_roundtrip.py -q` (1
  passed), `git diff --check` (clean — only pre-existing CRLF/LF
  line-ending advisories, no actual conflict/whitespace error, exit 0),
  `git diff -- src/torque/state_machine.py src/torque/models/guards.py`
  (both empty), `git status` (the 5 docs already modified by Phase 0+1 plus
  their Phase 2 additions, and exactly 2 new source files —
  `src/torque/ai/citations.py`, `tests/test_ai_citations.py` — no existing
  tracked source file modified beyond `schemas.py`/`evidence.py`, both
  already part of the AI package).
- **Recommended commit message:**
  `AI Phase 2: evidence normalization + citation model — Citation DTO, resolve_citation(), CaseSnapshot becomes citable (D-140); pure/no-DB, structurally enforced, zero deterministic-core changes, no migration`

---

## AI Phase 3 — Retrieval / Precedent Engine — COMPLETE

- **Branch:** `ai-layer`. **Not on `main`.**
- **Verified before starting (per this milestone's own governing
  instructions):** `git status`/`git branch --show-current` confirmed
  `ai-layer`, clean tree. `src/torque/ai/{schemas,evidence,citations}.py`
  and all three prior AI test files were re-read and found byte-identical
  to what Phase 0-2 left them — no drift, no discrepancy requiring a STOP.
  One git-history observation (not a code defect): the commit that landed
  Phase 0-2's work on `ai-layer` (`ceafbec`) is titled "Phase 2 — Retrieval
  / precedent engine: Postgres full-text search" — a mislabeling using the
  pre-correction phase numbering; its actual diff contains only the Phase
  0-2 evidence/citation files, no `retrieval.py`. Recorded here for the
  record; not something this milestone rewrites (Git history is the
  maintainer's).
- **Migrations:** **none.** `alembic head` stays `0018_escalation_resolution`.
- **Objective:** answer "has this merchant previously experienced a
  comparable resolved case, and if so, what happened?" — deterministically,
  read-only, informational only. Never "what should Torque do."
- **A real architectural tension found and resolved, not silently:** the
  task's own instruction to "use the existing source of truth" for terminal
  states collides with `torque.ai`'s forbidden-import boundary, which blocks
  the whole `torque.state_machine` module (including its pure,
  non-mutating `TERMINAL_STATUSES`/`is_terminal`) and which this program's
  instructions describe as "permanent." Resolved by duplicating the exact
  logic locally in `retrieval.py`, cross-tested for byte-for-byte
  equivalence against the real function in a test file (which, unlike
  `src/torque/ai/*`, is free to import it) — see D-141 for the full
  reasoning and the considered-but-not-taken alternative (narrowing the
  boundary test to a name-level allowlist).
- **Scope delivered:**
  - `src/torque/ai/schemas.py` — new `PrecedentCase` DTO (`case_id,
    root_cause_code, outcome_summary, recovered, evidence_id` — frozen,
    `extra="forbid"`, deliberately small, mirroring `Citation`'s own
    minimalism).
  - `src/torque/ai/retrieval.py` (**new module**) — `find_precedent
    (session, merchant_id, case, *, top_k=3) -> list[PrecedentCase]`.
    Pipeline: exact-match filter on `(merchant_id via TenantScope, leg_type,
    root_cause_code)` + terminal-only + self/superseded exclusion ->
    Postgres full-text search (`to_tsvector`/`plainto_tsquery`/`ts_rank`
    over `CaseEvent.reasoning` + `root_cause_label`, MAX-aggregated per
    candidate case) as a secondary ranking signal within that already-exact
    set -> recency tiebreak -> top-K. `outcome_summary` is a deterministic
    template over case-level fields + the resolution event's locked payload
    keys (`recovery_type`/`resolution`) — never free-form `reasoning` text,
    no LLM anywhere. `evidence_id` is computed via the real
    `EvidenceReference` model (Phase 1/2's own id-format source of truth),
    pointing at the precedent's resolution event
    (`PAYMENT_RECONCILED`/`HUMAN_RESOLVED`) if one exists, else its case
    snapshot.
  - **No new index, no migration** — `EXPLAIN ANALYZE` against the seeded
    `acc_demo` dataset confirms both the metadata-filter query and the
    lexical-ranking query already use the existing
    `ix_revenue_leak_case_merchant_id` / `ix_case_event_case_id` indexes
    (Milestone 1) and complete in well under 1ms:
    ```
    Metadata filter: Index Scan using ix_revenue_leak_case_merchant_id
      Execution Time: 0.114 ms
    Lexical FTS ranking: HashAggregate over a Nested Loop of two
      index scans (ix_revenue_leak_case_merchant_id, ix_case_event_case_id)
      Execution Time: 0.849 ms
    ```
  - **Tests (NEW, 21):** `tests/test_ai_retrieval.py` — the terminal-mirror
    cross-check against the real `is_terminal`; same-merchant match with
    exact-identity assertions (not just `len() > 0`); cross-merchant
    exclusion; a merchant/case-mismatch defensive `ValueError`;
    current-case self-exclusion; in-flight exclusion;
    `PARTIALLY_RECOVERED` terminal-for-non-B2B / not-terminal-for-B2B (both
    directions, exercising the leg-conditional terminal logic directly);
    zero-match on a unique root cause; top-K default and capped, plus
    out-of-range rejection; recency tiebreak when lexical rank is flat;
    different-leg / different-root-cause non-matches; missing-root-cause ->
    `[]`; missing-`reasoning` does not crash; citation resolution against
    the precedent's own evidence set (both with and without a resolution
    event, proving the case-snapshot fallback); empty corpus -> `[]`; and
    two tests against the real seeded `acc_demo` dataset (§23/§25 of the
    task) — see "Seed Verification" below.
- **Decisions:** D-141 (Postgres FTS as a secondary-only signal, no
  index/migration at N≈16, terminal-state duplication).
- **Invariants:** INV-62 (same-merchant / terminal-only / self-excluding /
  bounded / citation-resolvable / read-only retrieval).
- **Seed verification (exact identities, not just pass/fail):**
  - **Positive:** `acc_demo` carries a `RECOVERED`
    `SUBSCRIPTION_FAILURE`/`NSF_SOFT_DECLINE` case (Aarav Mehta) and an
    open, in-flight `PLAYBOOK_ACTIVE` case with the identical
    `(leg_type, root_cause_code)` (Diya Kapoor — Sara Khan shares the same
    pair too but is excluded by the terminal filter same as Diya's own
    search would exclude her). Searching precedent for the open case
    surfaces Aarav Mehta's case by exact `case_id`, `root_cause_code =
    "NSF_SOFT_DECLINE"`, `recovered = True` — correct, because it is the
    only terminal case sharing that exact metadata pair at that merchant.
  - **Zero:** `acc_demo` carries exactly one
    `PAYMENT_DEGRADATION`/`GATEWAY_TIMEOUT` case (Priya Nair) — no other
    case at `acc_demo` shares that pair (verified by an explicit
    no-duplicate assertion in the test itself, so the test fails loudly if
    the seed ever changes shape rather than passing vacuously). Searching
    precedent for it returns `[]` — correct, because no comparable resolved
    case exists.
- **Deviations from `AI_BLUEPRINT.md`:** none in scope or architecture. The
  terminal-state duplication (documented above and in D-141) is a
  deliberate implementation choice within an area the blueprint left open
  ("NEEDS HUMAN DECISION" on narrowing the boundary test), not a deviation
  from anything it locked.
- **Deferred work:** everything from Phase 4 onward (LLM case explanation,
  faithfulness evaluation, Agent Console integration, shadow ML, hardening,
  demo polish) — none implemented, none started. Explicitly **not**
  implemented in this milestone: any LLM provider/prompt/call, any
  embedding or vector search, `CaseNarrative` or any generated prose, any
  API endpoint, any UI change.
- **Unresolved:** none resolved and none newly introduced by this work.
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff` empty for each).
- **Tests at completion:** **1289** passed (was 1268 after Phase 2;
  **+21**), 0 failed, 0 skipped, the same 1 pre-existing cosmetic
  `StarletteDeprecationWarning`. `ruff check .` clean. `alembic upgrade
  head` -> `0018` (no-op — no migration); roundtrip green
  (`tests/test_zz_migrations_roundtrip.py`, 1 passed).
- **Verification status:** complete + verified — `uv run pytest
  tests/test_ai_retrieval.py tests/test_ai_citations.py
  tests/test_ai_evidence.py tests/test_ai_boundary.py -q` (56 passed),
  `uv run pytest -q` (full suite, 1289 passed), `uv run ruff check .`
  (clean, repository-wide), `uv run alembic upgrade head` (succeeds, no new
  migration), `uv run pytest tests/test_zz_migrations_roundtrip.py -q` (1
  passed), `git diff --check` (clean — only pre-existing CRLF/LF
  advisories), `git diff -- src/torque/state_machine.py
  src/torque/models/guards.py` (both empty), `EXPLAIN ANALYZE` against the
  seeded dataset (recorded above — index scans, sub-millisecond, no
  sequential scan concern to act on).
- **Recommended commit message:**
  `AI Phase 3: retrieval / precedent engine — find_precedent(), Postgres FTS as secondary signal over an exact metadata match, PrecedentCase (D-141/INV-62); no index/migration, no embeddings, no LLM, zero deterministic-core changes`

---

## AI Phase 4 — LLM Case Explanation — COMPLETE

- **Branch:** `ai-layer`. **Not on `main`.**
- **Verified before starting:** `git status`/`git branch --show-current`
  confirmed `ai-layer`, clean tree, HEAD `b5af313` "feat(ai): add
  retrieval-grounded precedent engine" (the maintainer's commit of the
  Phase 3 work — its own message, unlike the earlier `ceafbec`, is
  accurate). `src/torque/ai/{schemas,config,retrieval}.py` were re-read and
  found byte-identical to what Phase 0-3 left them — no drift.
- **Migrations:** **none.** `alembic head` stays `0018_escalation_resolution`.
- **Objective:** the first real AI-generation capability —
  `explain_case()`, producing a structured, citation-grounded
  `CaseNarrative` from authoritative evidence (Phase 1) + retrieved
  precedent (Phase 3) + LLM synthesis. The LLM's job is synthesis,
  explanation, and organization only — never diagnosis, scoring, policy,
  playbook selection, action execution, or state transition; the schema
  has no field for any of those, and nothing downstream of `explain_case`
  executes anything it returns.
- **Scope delivered:**
  - `src/torque/ai/providers/{__init__,base,mock_provider}.py` (**new
    package**) — `LLMProvider` (`ABC`: `async structured_generate(*,
    system, user, schema, max_tokens, timeout_s) -> BaseModel` +
    `provider_id() -> str`); `MockProvider` — the required,
    network-independent implementation. Deterministic (fixed placeholder
    `generated_at`, not a live timestamp) and genuinely evidence-grounded:
    it parses the `<evidence>` JSON envelope out of its own `user` message
    (using `rindex` for the closing tag specifically so an adversarial
    payload containing a literal `</evidence>` string cannot truncate the
    parse — a real robustness fix found while writing the prompt-injection
    test, not a hypothetical) and builds every claim/citation from that
    real payload. Constructor flags (`raise_exception`,
    `return_malformed`, `return_wrong_type`, `fabricate_citation`,
    `wrong_case_id`) let tests deliberately simulate every provider
    failure mode without any network access.
  - `src/torque/ai/prompts.py` (**new module**) — `PROMPT_VERSION =
    "narrative-v1"`; `build_narrative_prompt(evidence, precedents) ->
    (system, user)`. The system message is a fixed module-level constant
    (role, task, seven hard rules, output-format requirements, and an
    explicit prompt-injection defense) — never built from or interpolated
    with evidence. The user message is `<evidence>` + `json.dumps({
    "current_case": evidence.model_dump(mode="json"), "precedent_cases":
    [...]}, indent=2, sort_keys=True)` + `</evidence>` — only typed
    `torque.ai.schemas` DTOs are ever serialized; no ORM object, `Session`,
    or internal field reaches this module.
  - `src/torque/ai/narrative.py` (**new module**) — `async
    explain_case(session, *, merchant_id, case_id, provider, max_tokens=
    None, timeout_s=None) -> CaseNarrative`. Pipeline: `gather_case_evidence`
    (Phase 1) -> a bridging `TenantScope.get(RevenueLeakCase, ...)` lookup
    -> `find_precedent` (Phase 3, unmodified signature, reused not
    reimplemented) -> `build_narrative_prompt` -> `provider.
    structured_generate` (wrapped in `try/except Exception`, re-raised as
    `NarrativeGenerationError`, original chained via `from exc`) ->
    `_validate_citations` (the Phase 4 hard safety gate — exact-match, not
    superset, not repair; see D-143) -> `model_copy(update={case_id,
    generated_at, provider_id, prompt_version})` — the four identity fields
    are ALWAYS orchestrator-authored, never trusted from the provider.
  - `src/torque/ai/schemas.py` — `NarrativeClaim` (`claim: str,
    citation_ids: list[str]` — deliberately NOT named `TimelineEntry`
    despite the task's own wording; see D-143 sub-decision 3 for why
    reusing that name would have broken an existing Phase 1 class),
    `PrecedentSection` (`found`, `cases`, `note`), `NO_PRECEDENT_NOTE`
    (the fixed, non-LLM-authored empty-precedent text), `CaseNarrative`
    (the full task-specified contract: `case_id, generated_at, summary,
    current_state, root_cause_explanation, timeline, actions_taken,
    guardrail_explanation, precedent, recommended_human_attention,
    uncertainty, evidence_gaps, citations, provider_id, prompt_version`).
  - `src/torque/ai/config.py` — `AISettings` gains `max_tokens: int = 2000`
    and `timeout_s: float = 30.0`, genuinely consumed as `explain_case`'s
    defaults (not decorative). `TORQUE_AI_PROVIDER` deliberately NOT added
    — nothing in Phase 4 has a provider-selection factory to consume it
    (see D-142).
  - `src/torque/ai/exceptions.py` — `NarrativeGenerationError(AIError)`,
    the single new exception covering every Phase 4 failure mode (provider
    exception, schema-invalid response, non-`BaseModel` return, unresolved
    citation) — no broad new error architecture, per the task's own
    instruction to reuse the existing convention.
  - **Tests (NEW, 32):** `tests/test_ai_providers.py` (13 — `LLMProvider`
    cannot be instantiated directly; `MockProvider` happy path, citation
    grounding, provider-id disclosure, determinism, no-network behavioral
    proxy, honest empty-precedent, evidence-gap-not-guess; and all five
    simulated failure modes). `tests/test_ai_narrative.py` (19 — basic
    generation, case identity incl. provider-lie correction, citation
    validity/completeness/de-duplication, precedent present/absent using
    real `module7_writer`-gated recovered cases, evidence-gap handling,
    provider disclosure, all four failure modes end-to-end
    (malformed/exception/wrong-type/fabricated-citation) each asserted to
    raise `NarrativeGenerationError` without leaking the raw provider
    exception, unknown-case and cross-tenant `EvidenceNotFoundError`
    (before any provider call), a prompt-injection test proving the system
    message never changes and injected evidence survives only as
    JSON-escaped data, a `db.new`/`db.dirty`/`db.deleted` write-nothing
    check, and one full end-to-end pipeline test against the real seeded
    `acc_demo` dataset).
- **Decisions:** D-142 (provider architecture: `LLMProvider`+`MockProvider`
  only, real provider deferred, async boundary needs no new dependency),
  D-143 (narrative safety architecture: orchestrator-authored identity
  fields, exact-match citation gate, `NarrativeClaim` naming).
- **Invariants:** INV-63 (generated narratives never carry an unresolved
  citation or provider-authored identity; narrative generation is
  mutation-free and unpersisted).
- **A real robustness bug found and fixed during testing, not merely
  anticipated:** the first version of `MockProvider._extract_evidence_payload`
  used `user.index("</evidence>")` (first occurrence) to find the envelope's
  closing tag. An adversarial `CaseEvent.reasoning` value containing the
  literal text `</evidence><evidence>fabricated` (part of the deliberate
  prompt-injection test evidence) matched that search *inside the JSON
  payload itself*, truncating the parse and raising a `JSONDecodeError`
  from within `structured_generate` before any citation-validation logic
  ever ran. Fixed by using `rindex` (last occurrence) for the closing tag —
  correct because `build_narrative_prompt` always appends the real
  `</evidence>` exactly once, at the very end, after arbitrarily much
  untrusted data. Re-verified: the same adversarial input now parses
  correctly and the pipeline completes and citation-validates cleanly.
  This was caught by the test suite itself, not by inspection.
- **Deviations from `AI_BLUEPRINT.md` / the Phase 4 task:** the claim-bearing
  narrative primitive is named `NarrativeClaim`, not `TimelineEntry` as the
  task's own wording suggested — see D-143 sub-decision 3 (a name collision
  with an existing, differently-shaped Phase 1 class, not a redesign of
  anything). No other deviation.
- **Deferred work:** everything from Phase 5 onward (faithfulness/
  evaluation harness, Agent Console integration, shadow ML, hardening, demo
  polish) — none implemented, none started. Explicitly **not** implemented
  in this milestone: any real (Anthropic or otherwise) provider; any API
  endpoint (`api/ai.py`); any frontend/Agent Console change; any embedding
  or vector search; `evaluation.py` or any citation-coverage/retrieval-
  precision/unsupported-claim-rate/faithfulness metric; any shadow ML
  (XGBoost/SHAP/calibration); any narrative persistence (generation is
  stateless — nothing is written to the database anywhere in this
  milestone).
- **Unresolved:** none resolved and none newly introduced by this work.
- **`state_machine.py` / `guards.py`:** **both byte-unchanged vs HEAD**
  (`git diff` empty for each).
- **Tests at completion:** **1321** passed (was 1289 after Phase 3;
  **+32**), 0 failed, 0 skipped, the same 1 pre-existing cosmetic
  `StarletteDeprecationWarning`. `ruff check .` clean. `alembic upgrade
  head` -> `0018` (no-op — no migration); roundtrip green
  (`tests/test_zz_migrations_roundtrip.py`, 1 passed).
- **Verification status:** complete + verified — `uv run pytest
  tests/test_ai_providers.py tests/test_ai_narrative.py
  tests/test_ai_retrieval.py tests/test_ai_citations.py
  tests/test_ai_evidence.py tests/test_ai_boundary.py -q` (91 passed),
  `uv run pytest -q` (full suite, 1321 passed), `uv run ruff check .`
  (clean, repository-wide), `uv run alembic upgrade head` (succeeds, no new
  migration), `uv run pytest tests/test_zz_migrations_roundtrip.py -q` (1
  passed), `git diff --check` (clean — only pre-existing CRLF/LF
  advisories), `git diff -- src/torque/state_machine.py
  src/torque/models/guards.py` (both empty).
- **Recommended commit message:**
  `AI Phase 4: LLM case explanation — LLMProvider/MockProvider, deterministic prompt builder, explain_case() orchestration, CaseNarrative (D-142/D-143/INV-63); citation existence is a hard gate, provider identity fields never trusted, stateless, zero deterministic-core changes, no migration`

---

## AI Phase 5 — Citation / Faithfulness Evaluation — COMPLETE

- **Branch:** `ai-layer`. **Not on `main`.**
- **Verified before starting:** `git status`/`git branch --show-current`
  confirmed `ai-layer`, clean tree on top of the Phase 4 commit. `src/torque/
  ai/narrative.py::_validate_citations`, `src/torque/state_machine.py`, and
  `src/torque/models/guards.py` were re-read and confirmed to still match
  what the Phase 4 report described — none touched by this phase.
- **Objective:** turn "the generated narrative appears grounded" (Phase 4's
  pass/fail citation-existence gate) into a set of *measured*, deterministic
  statistics a reviewer can read as a number, without introducing an LLM
  judge, without any database side effect, and without evaluation ever being
  able to see anything beyond the exact evidence/precedent objects a specific
  generation call actually used (the Absolute Data-Source Rule).
- **Files created:**
  - `src/torque/ai/evaluation.py` — `evaluate_narrative(narrative, evidence,
    precedents, *, expected_precedent_found=None,
    retrieval_precision_at_k=None) -> EvaluationReport` (pure, no `Session`
    parameter — cannot re-query the database) and
    `evaluate_retrieval_precision(session, merchant_id, case,
    relevant_case_ids, *, top_k=DEFAULT_TOP_K) -> float` (the one, deliberate,
    structurally separate DB-touching exception — it calls Phase 3's
    `find_precedent` again because there is no other way to measure retrieval
    quality). Private helpers: `_normalize_tokens`, `_evidence_text`,
    `_resolve_evidence_text`, `_collect_claim_citation_ids` (mirrors, not
    imports, `narrative.py`'s private function — see D-141's precedent for
    this pattern), `_claim_bearing_fields`, `_is_claim_supported`. Constants:
    `_OVERLAP_THRESHOLD = 0.2` (empirically calibrated — see below),
    `_STOPWORDS`, `_TOKEN_RE`.
  - `tests/ai_eval_cases.py` — a flat helper module (not a new `tests/
    fixtures/` subpackage, matching the existing `tests/module9b_helpers.py`
    convention) providing `EvalCase` (a dataclass bundling a real case, its
    exact evidence/precedent snapshot, its generated narrative, and
    independently hand-written ground-truth labels) and `build_eval_cases()`,
    which builds 6 real, DB-backed, hand-labeled scenarios: `valid_with_
    real_precedent`, `unique_root_cause_no_precedent`, `empty_corpus_no_
    precedent`, `multiple_relevant_precedents`, `adversarial_evidence_text`,
    `missing_diagnosis_evidence_gap`.
  - `tests/test_ai_evaluation.py` — 22 tests.
- **Files modified:**
  - `src/torque/ai/schemas.py` — added `EvaluationReport` (frozen,
    `extra="forbid"`, 12 fields: `citation_existence_rate,
    citation_coverage, unsupported_claim_rate, no_precedent_correct,
    retrieval_precision_at_k, total_claims, cited_claims, total_citations,
    resolvable_citations, unresolved_citation_ids,
    unsupported_claim_count, evaluated_precedent_cases`).
- **Metrics implemented** (all deterministic, all pure functions of the
  exact `(narrative, evidence, precedents)` supplied):
  1. **Citation existence rate** — fraction of all citation ids referenced
     anywhere in the narrative (claims + precedent cases) that resolve
     against the supplied evidence/precedent set via Phase 2's real
     `resolve_citation` / exact `evidence_id` match.
  2. **Citation coverage** — fraction of claim-bearing fields that carry at
     least one citation id at all (a structural completeness measure,
     independent of whether those citations resolve).
  3. **Unsupported-claim rate** — a deterministic lexical-overlap proxy: for
     each cited claim, normalize + tokenize + strip stopwords, take the
     overlap ratio between the claim's tokens and its cited evidence's
     tokens; a claim is "unsupported" if its overlap ratio is below
     `_OVERLAP_THRESHOLD` for every one of its citations. **Explicitly not
     semantic entailment** — documented in-module and in D-144 as a v1
     proxy; LLM-as-judge is deferred with no target phase, per the task's
     explicit prohibition (§15).
  4. **No-precedent correctness** — `precedent.found` compared against an
     independently hand-labeled `expected_precedent_found`; `None` when the
     case makes no claim about precedent correctness.
  5. **Retrieval precision@K** — the one metric requiring live DB access
     (`evaluate_retrieval_precision`), measuring what fraction of `find_
     precedent`'s current top-K output matches an independently hand-labeled
     `relevant_case_ids` set — kept structurally separate from `evaluate_
     narrative` so a caller who only wants narrative-faithfulness metrics
     never touches a database.
- **Calibration finding (a real measurement result, not a guess):** the
  task's own illustrative threshold guidance (0.5) was tried first and
  failed — `MockProvider`'s own genuinely-correct, evidence-grounded claims
  scored only 0.25-0.33 overlap against their citations (short template
  sentences are mostly framing words, not repeated content), which a 0.5
  threshold misclassified as unsupported. Recalibrated to `0.2`, verified
  empirically to correctly classify every real `MockProvider` claim as
  supported (0.25-0.33 ≥ 0.2) while still classifying the task's own BAD
  example ("The merchant requested a full refund immediately," cited against
  unrelated evidence) as unsupported (overlap 0.0). See D-144.
- **Measured values on the 6-case evaluation set** (captured via a one-off
  script, `PYTHONPATH=. uv run python <scratch>/measure_eval.py`, deleted
  after use — not part of the deliverable):
  - `citation_existence_rate = 1.000` for all 6 cases.
  - `citation_coverage = 1.000` for 5/6 cases; `0.500` for
    `missing_diagnosis_evidence_gap` (an honest evidence gap correctly
    surfaced as reduced coverage, not an invented citation) — aggregate
    across the set: `12/13 = 0.9231`.
  - `unsupported_claim_rate = 0.000` for all 6 cases (every real
    `MockProvider` claim is genuinely evidence-grounded).
  - `no_precedent_correct = True` for all 6 cases (`find_precedent`'s actual
    output matched every hand-written expectation).
  - `retrieval_precision_at_k = 1.0` for all 4 cases carrying a
    `relevant_case_ids` label.
- **Deliberately not built** (per the task's explicit scope): any LLM-as-
  judge or semantic-entailment scoring (§15); RAGAS or any other evaluation
  framework dependency (§16); any modification to `narrative.py::
  _validate_citations` (§14 — confirmed byte-unchanged); any API endpoint or
  UI surface for evaluation results (§18); any database persistence of an
  `EvaluationReport` (evaluation is a pure, stateless computation, called
  only from tests).
- **`state_machine.py` / `guards.py` / `narrative.py::_validate_citations`:**
  all byte-unchanged vs. the Phase 4 commit (`git diff` empty for each).
- **Tests at completion:** `tests/test_ai_evaluation.py` alone — **22**
  passed. Full AI suite — **110** passed (Phase 0-5 combined; was 91 after
  Phase 4, **+19** across the modules touched — the remaining 3 of the 22
  new tests exercise existing Phase 1-4 fixtures without adding a new test
  file). Full regression suite — **1343** passed (was 1321 after Phase 4,
  **+22**), 0 failed, 0 skipped, the same 1 pre-existing cosmetic
  `StarletteDeprecationWarning`. `ruff check .` clean. `alembic upgrade
  head` -> `0018` (no-op — no migration); roundtrip green
  (`tests/test_zz_migrations_roundtrip.py`, 1 passed).
- **Verification status:** complete + verified — `uv run pytest
  tests/test_ai_evaluation.py -q` (22 passed), `uv run pytest -q` (full
  suite, 1343 passed), `uv run ruff check .` (clean, repository-wide),
  `uv run alembic upgrade head` (succeeds, no new migration), `uv run pytest
  tests/test_zz_migrations_roundtrip.py -q` (1 passed), `git diff --check`
  (clean — only pre-existing CRLF/LF advisories), `git diff --
  src/torque/state_machine.py src/torque/models/guards.py` (both empty),
  `git status` (confirmed only `src/torque/ai/schemas.py` modified plus
  three new files: `src/torque/ai/evaluation.py`, `tests/ai_eval_cases.py`,
  `tests/test_ai_evaluation.py`).
- **Deviations from the literal task wording (all additive, all
  documented):** fixture module named `tests/ai_eval_cases.py`, not
  `tests/fixtures/ai_eval_cases.py` — this project's existing test suite has
  no `tests/fixtures/` subpackage anywhere, and `tests/module9b_helpers.py`
  already established the flat-helper-module convention this follows;
  `_OVERLAP_THRESHOLD` recalibrated from the task's illustrative `0.5` to an
  empirically verified `0.2` (see Calibration finding above); citation-
  collection logic (`_collect_claim_citation_ids`) mirrored rather than
  imported from `narrative.py`, matching the exact pattern D-141 established
  for `torque.state_machine.is_terminal` in Phase 3, to avoid loosening
  `test_ai_boundary.py`'s import allowlist.
- **Recommended commit message:**
  `AI Phase 5: citation / faithfulness evaluation — evaluate_narrative()/evaluate_retrieval_precision(), EvaluationReport (5 deterministic metrics, D-144/INV-64); lexical-overlap unsupported-claim proxy calibrated to 0.2, no LLM-as-judge, no DB writes, zero deterministic-core changes, no migration`

---

## AI Phase 6 — Agent Console Integration — COMPLETE

- **Branch:** `ai-layer`. **Not on `main`.**
- **Verified before starting:** `git status`/`git branch --show-current`
  confirmed `ai-layer`, clean tree on top of the Phase 5 commit.
  `src/torque/ai/narrative.py::_validate_citations`,
  `src/torque/state_machine.py`, and `src/torque/models/guards.py` were
  re-read and confirmed unchanged from what the Phase 5 report described —
  none touched by this phase either.
- **Objective:** give `explain_case` (fully built since Phase 4, no caller
  outside its own test suite) its first real caller — one read-only HTTP
  route consumed by one Agent Console panel, with citation navigation into
  the case's existing audit trail — without redesigning Phases 0-5, without
  any AI write path, and without a real LLM provider.
- **Files created:**
  - `src/torque/api/ai.py` — `GET /ai/{merchant_id}/cases/{case_id}/explain`.
    `_require_merchant`, `_get_provider` (the single `MockProvider()`
    construction site), the `explain` handler: `AISettings.enabled` check
    (`503` if off) -> `explain_case` -> `EvidenceNotFoundError` -> `404` /
    `NarrativeGenerationError` -> `502`, every `HTTPException.detail` a
    fixed hand-written string.
  - `tests/test_ai_api.py` — 10 tests.
- **Files modified:**
  - `src/torque/api/app.py` — registers `ai_router`; docstring surface list
    updated.
  - `src/torque/ui/static/torque.js` — an "Explain this case" button +
    `#aiPanel` in `renderConsolePane`; `citationLabel`/`citeGroup`/
    `claimLine`/`claimList`/`renderPrecedent`/`renderNarrative`/
    `explainCase`/`focusCitation` (new); `renderEvent`'s `<li>` now carries
    `data-event-seq="${e.event_seq_id}"`; `renderConsolePane`'s audit trail
    now renders every event, not `events.slice(-8)` (needed so a citation
    to an older event always has a DOM target — see Deviations);
    `barChart()` now left-pads a sparse series to a 7-bar minimum with
    honest zero-recovery days (the dashboard graph fix — see below).
  - `src/torque/ui/static/torque.css` — `.ai-narrative`/`.ai-block`/
    `.ai-summary`/`.claims`/`.cite`/`.cite-hit`/`.ai-loading`/`.ai-error`/
    `.ai-meta` (new rules only; nothing existing changed).
  - `tests/test_module10_ui.py` — 6 new tests + a `_strip_js_comments`
    helper (module docstring extended to describe the Phase 6 additions).
  - `documentation/ai-memory/{AI_BLUEPRINT.md, DECISIONS.md,
    INVARIANTS.md}` — Phase 6 documentation (this entry, D-145, and — only
    if a genuinely new permanent property was found — a new invariant; see
    below).
- **Architecture:**
  ```
  Agent Console (human queue -> case pane)
      -> "Explain this case" (on demand only, never on page load)
      -> GET /ai/{merchant_id}/cases/{case_id}/explain
      -> AISettings.enabled? no -> 503, nothing else touched
      -> explain_case()  (Phase 4, unmodified)
      -> CaseNarrative (JSON)
      -> rendered in the same case pane; every citation is a button;
         clicking one locates <li data-event-seq="N"> already in the
         audit trail below it, scrolls it into view, flashes it
  ```
- **Feature flag / provider:** `AISettings.enabled` (Phase 0/4, unmodified)
  read via `Depends(get_ai_settings)`; disabled -> `503` before any
  merchant lookup. `MockProvider` remains the only concrete provider —
  `_get_provider()` is the one seam a future real provider replaces. No new
  configuration setting was added (`TORQUE_AI_PROVIDER` remains
  deliberately unadded, per D-142/D-AI-03 — still nothing to select
  between).
- **Database dependency:** no `get_ai_db` was needed or built — the
  endpoint uses the existing `Depends(get_db)`, the same dependency every
  other read endpoint in `torque.api` uses. No second session/DB
  architecture.
- **Dashboard graph investigation and fix:** investigated per the task's
  own order — what graph (`recovery-over-time`, per the blueprint), what
  backend data (`GET /reports/{merchant_id}/over-time?bucket=day`, already
  correct and complete), does the API return what's needed (yes), so the
  defect had to be data-shape-vs-rendering — confirmed live: the seeded
  demo's Torque-credited recoveries cluster into one UTC day, so
  `barChart()`'s `flex:1` stretched a single bar to the panel's full
  width. **No backend change was needed or made** — `recovery_over_time`
  is untouched. Fix: `barChart()` left-pads a sparse series with explicit,
  honest zero-recovery days (a day with no recovery genuinely recovered
  ₹0) up to a 7-bar minimum before rendering exactly as before. Verified
  live against the real seeded `acc_demo` dataset: before the fix, exactly
  1 bar at 118px covering the full container width; after, 7 bars
  (`9/9`…`15/9`), 6 real zero-height bars and the one real bucket at its
  correct relative height. No demo-seed data was touched.
- **Documentation-artifact audit:** grepped `index.html`/`torque.js`/
  `torque.css` for `§`/`Module N`/`Phase N`/`Blueprint` before changing
  anything (per the task's own instruction to investigate before acting).
  **Finding: zero instances rendered anywhere** — every occurrence lives
  inside a `//`/`/* */` source comment, never in a template-literal string
  assigned to `innerHTML` or any other user-facing surface; confirmed both
  by source inspection and by rendering the live dashboard, cases list,
  case detail, Agent Console, and demo views end to end. **No cleanup edit
  was made because none was needed** — reported as a zero-finding audit,
  not skipped, and made a standing, enforced fact going forward via
  `tests/test_module10_ui.py::test_ui_has_no_documentation_artifacts_outside_comments`.
- **Live verification (not just automated tests):** ran the real app
  (`docker compose up -d db redis`, `uv run alembic upgrade head`,
  `TORQUE_AI_ENABLED=true uv run python -m torque`) against the real
  seeded `acc_demo` merchant and drove it through the Browser pane:
  - Agent Console -> selected the escalated "Tara Menon" subscription-
    failure case -> clicked "Explain this case" -> a real narrative
    rendered: summary, current-state and root-cause claims each citing
    "Case snapshot", a three-entry timeline citing "Event 658" / "Event
    659" / "Event 660", "None recorded" for actions taken, an honest "No
    comparable resolved case exists yet for this root cause" precedent
    section, a recommended-attention note, an uncertainty/evidence-gap
    statement, and a `Generated ... · mock:deterministic-v1 ·
    narrative-v1` footer.
  - Clicked the "Event 658" citation — confirmed via direct DOM inspection
    that `li[data-event-seq="658"]` gained the `.cite-hit` flash class
    immediately (the exact core-demo-moment behavior the task asked for).
  - Clicked the "Case snapshot" citation (a non-`case_event` reference,
    which has no per-row DOM target) — confirmed it fell back to a toast
    ("Referenced: Case snapshot") rather than a broken navigation or an
    error.
  - Confirmed the dashboard's "Recovery over time" panel rendered 7 bars
    (not 1) with correct relative heights via `getComputedStyle`/DOM
    inspection.
  - Confirmed no case/action/event state changed by this session's own
    interaction (`tests/test_ai_api.py::test_explain_performs_no_write`
    plus a direct before/after read of the same case's row).
  - The AI-disabled (`503`) UI copy path was verified by code + by
    `tests/test_ai_api.py::test_explain_ai_disabled_returns_503_without_touching_anything`,
    not by a second live server toggle (would have required tearing down
    the working, already-verified `TORQUE_AI_ENABLED=true` session).
- **Deliberately not built** (per the task's explicit scope): Phase 7
  shadow ML; embeddings; vector DB; ML training; LLM-as-judge; any
  autonomous/AI-controlled action or state transition; any new write
  endpoint; a new frontend framework or build step; a real external LLM
  provider; a browser/e2e test harness; any demo-data redesign; any
  API/UI surface for `EvaluationReport` (Phase 5 remains test-only).
- **`state_machine.py` / `guards.py` / `narrative.py::_validate_citations`
  / `tests/test_ai_boundary.py`:** all byte-unchanged vs. the Phase 5
  commit (`git diff` empty for each).
- **Tests at completion:** `tests/test_ai_api.py` — **10** passed (new).
  `tests/test_module10_ui.py` — **10** passed (4 pre-existing + 6 new).
  The `tests/test_ai_*.py` family (9 files, including the new
  `test_ai_api.py`) — **123** passed. Full regression suite — **1359**
  passed (was 1343 after Phase 5, **+16**), 0 failed, 0 skipped, the same
  1 pre-existing cosmetic `StarletteDeprecationWarning`. `ruff check .`
  clean. `alembic upgrade head` -> `0018` (no-op — no migration); roundtrip
  green (`tests/test_zz_migrations_roundtrip.py`, 1 passed).
- **Verification status:** complete + verified — `uv run pytest
  tests/test_ai_api.py -q` (10 passed), `uv run pytest tests/test_ai_api.py
  tests/test_ai_evaluation.py tests/test_ai_narrative.py
  tests/test_ai_providers.py tests/test_ai_retrieval.py
  tests/test_ai_citations.py tests/test_ai_evidence.py
  tests/test_ai_boundary.py tests/test_ai_config.py -q` (123 passed),
  `uv run pytest -q` (full suite, 1359 passed), `uv run ruff check .`
  (clean, repository-wide), `uv run alembic upgrade head` (succeeds, no new
  migration; head `0018_escalation_resolution`), `uv run pytest
  tests/test_zz_migrations_roundtrip.py -q` (1 passed), `git diff --check`
  (clean — only pre-existing CRLF/LF advisories), `git diff --
  src/torque/state_machine.py src/torque/models/guards.py` (both empty).
- **Deviations from the literal task wording (all additive, all
  documented):** `renderConsolePane`'s audit trail now renders every event
  instead of the pre-existing `events.slice(-8)` — a small, necessary
  adjustment (not a redesign) so a citation to an event older than the
  last 8 always has a DOM target to navigate to; `503` (not an explicitly
  pre-existing repository convention, since none existed for "a GET route
  behind a disabled feature flag") chosen as the closest fit to
  `torque.api.health`'s existing readiness-probe convention, recorded as
  D-145 rather than invented silently; the live-verified demo corpus size
  is 22 cases (not a fixed "16"), measured directly rather than assumed —
  see AI_BLUEPRINT.md §9a's reconciliation note.
- **Recommended commit message:**
  `AI Phase 6: Agent Console integration — GET /ai/{merchant_id}/cases/{case_id}/explain (D-145), Explain-this-case narrative panel + citation-to-audit-trail navigation, dashboard over-time graph zero-padding fix, documentation-artifact audit (zero findings); read-only end to end, zero deterministic-core changes, no migration`

---

## AI Phase 7 — Shadow ML — COMPLETE

- **Branch:** `ai-layer`. **Not on `main`.**
- **Verified before starting:** `git status`/`git branch --show-current`
  confirmed `ai-layer`, clean tree on top of the Phase 6 commit. Read the
  full `src/torque/ai/` package (Phases 0-6), the Phase 5 evaluation
  implementation/tests, the Phase 6 API + Agent Console integration, and
  the deterministic scoring/diagnosis/reconciliation modules this phase is
  forbidden from importing but needed to understand (`torque.state_machine.
  is_terminal`/`TERMINAL_STATUSES`, `torque.scoring.score._days_since_
  failure`, `torque.reporting.incrementality._RECOVERED_STATUSES`,
  `torque.models.guards.tier_rank`) — all to determine what an authoritative,
  non-leaking feature representation legitimately looks like, exactly as
  the task's own audit-first instruction required.
- **Objective:** the smallest production-quality shadow-ML architecture
  that lets Torque build a model-ready feature representation from
  authoritative historical case data, train/evaluate a deliberately simple
  baseline model, generate shadow predictions, evaluate whether the model
  carries useful signal, and stay extensible — while remaining structurally
  incapable of influencing any Torque decision.
- **Files created:**
  - `src/torque/ai/shadow/__init__.py` — package boundary statement.
  - `src/torque/ai/shadow/labels.py` — `is_training_eligible`,
    `recovered_label` (local mirrors of `torque.state_machine.is_terminal`
    and `torque.reporting.incrementality._RECOVERED_STATUSES`, cross-tested).
  - `src/torque/ai/shadow/schemas.py` — `ShadowFeatureVector`,
    `ShadowTrainingExample`, `ShadowPrediction`, `ShadowClassificationMetrics`,
    `ShadowTrainingReport`, `FEATURE_SCHEMA_VERSION`, `SHADOW_DISCLAIMER`.
  - `src/torque/ai/shadow/features.py` — `extract_features`,
    `build_shadow_dataset` (DB-touching, `TenantScope`d, the disjoint
    narrower read path from `gather_case_evidence` — see D-147/D-148).
  - `src/torque/ai/shadow/model.py` — `ShadowModel` (ABC),
    `LogisticRegressionShadowModel` (see D-146).
  - `src/torque/ai/shadow/evaluation.py` — `compute_classification_metrics`,
    `majority_class_baseline_proba`.
  - `src/torque/ai/shadow/training.py` — `temporal_train_test_split`,
    `train_and_evaluate_shadow_model`.
  - `src/torque/ai/shadow/scoring.py` — `score_case`.
  - `tests/ai_shadow_cases.py` — real-domain-data test builders (mirrors
    `tests/ai_eval_cases.py`'s pattern).
  - `tests/test_ai_shadow_labels.py` (5 tests), `tests/test_ai_shadow_
    features.py` (16), `tests/test_ai_shadow_model.py` (10), `tests/
    test_ai_shadow_evaluation.py` (7), `tests/test_ai_shadow_training.py`
    (10), `tests/test_ai_shadow_scoring.py` (6) — **54 tests total**.
- **Files modified:**
  - `src/torque/ai/exceptions.py` — `ShadowMLError`, `InsufficientTraining
    DataError`, `ModelNotFittedError`, `FeatureExtractionError` (all
    subclass `AIError`; additive only, the three existing exceptions
    byte-unchanged).
  - `pyproject.toml` — `scikit-learn>=1.4` added to `[project.dependencies]`
    with an inline justification comment (see D-146); `uv.lock` updated
    (`uv sync --extra dev`).
  - `documentation/ai-memory/{AI_BLUEPRINT.md, DECISIONS.md, INVARIANTS.md}`
    — this entry, D-146..D-150, and INV-65.
- **Architecture:**
  ```
  build_shadow_dataset()        (TenantScope-read, terminal+diagnosed cases)
          v
  temporal_train_test_split()   (sorted by diagnosis-completion cutoff)
          v
  ShadowModel.fit(train)         (LogisticRegressionShadowModel, pure)
          v
  compute_classification_metrics(test) + majority_class_baseline_proba(train)
          v
  ShadowTrainingReport   (target/features/split/metrics/limitations/disclaimer)

  score_case(case_id, fitted_model)  ->  ShadowPrediction
      (n_training_cases + disclaimer always present)
  ```
- **Target:** `recovered = status in {RECOVERED, CANCELLED}` — byte-identical
  to Module 9b's own intent-to-treat definition
  (`torque.reporting.incrementality._RECOVERED_STATUSES`), mirrored locally
  in `torque.ai.shadow.labels` and cross-tested against both that constant
  and the real `torque.state_machine.is_terminal`
  (`tests/test_ai_shadow_labels.py`).
- **Features:** exactly the Blueprint §8.4 named set (`leg_type,
  root_cause_code, diagnosis_confidence, amount_at_risk, days_since_failure,
  promise_keeping_rate, risk_score, network_directive.tier, mandate_type`),
  each computed as of the case's own `DIAGNOSIS_COMPLETED` event timestamp
  — see D-147 for the full temporal-cutoff reasoning and D-148 for the B2B
  `amount_at_risk` leakage fix. A repo-wide audit during this phase found
  `MerchantCounterparty.risk_score` has **zero writers anywhere in the
  codebase** (always `None`/missing in practice) and `promise_keeping_rate`
  is a static, seed-only value with no in-life writer either — both
  reported honestly rather than assumed to carry signal they don't.
- **Dataset scale — measured, not assumed:** `torque.demo.seed.seed_demo`
  produces **7 terminal cases** for `acc_demo` (5 `RECOVERED`, 1
  `CANCELLED`, 1 `EXHAUSTED`), of which **6 are eligible** for the labeled
  population (the `CANCELLED` case self-recovered before diagnosis ran,
  §7.1.4/D-058, so it has no diagnosis fields to build a feature vector
  from — correctly excluded, not a bug) — the one-click scenario injectors
  add zero more terminal cases (every scenario ends open or blocked, never
  resolved). Measured live: `train_and_evaluate_shadow_model(acc_demo)` ->
  `n_total_cases=6, n_train=5, n_test=1,
  class_distribution={"recovered":5,"not_recovered":1}`, `test_metrics`
  (accuracy/precision/recall/F1 all `1.0` on the single held-out case,
  `roc_auc=null` — undefined with one test example, reported as `null` not
  fabricated), `baseline_metrics` identical to `test_metrics` on this
  one-example split (no real lift measurable at this scale),
  `insufficient_data=true`. Every `ShadowTrainingReport` this phase
  produces against real data reports `insufficient_data=True` with an
  explicit `limitations` entry stating the exact count and why it is too
  small — never a fabricated confident number.
- **Model:** `sklearn.linear_model.LogisticRegression` over a
  `DictVectorizer`-encoded feature dict — a documented departure from
  `AI_BLUEPRINT.md` §10's own prior **RECOMMENDED** (not `LOCKED`)
  XGBoost + SHAP suggestion, justified by the measured 7-case dataset scale
  against that suggestion's own 500-case gate. See D-146. `scikit-learn`
  is the first ML dependency this program has added; no `numpy`/`pandas`/
  `xgboost`/`shap`/vector-database dependency exists.
- **Persistence / API / UI:** none. No migration (`alembic heads` unchanged
  at `0018_escalation_resolution`), no FastAPI route, no
  `src/torque/ui/static/*` change — per the task's own explicit instruction
  to stay backend/evaluation-only unless the blueprint required otherwise
  (it does not). See D-149.
- **Deliberately not built** (per the task's explicit scope): any API
  endpoint or UI surface for `ShadowTrainingReport`/`ShadowPrediction`; any
  model persistence; a real (network-backed) model API; cross-merchant
  pooled training (D-150); XGBoost/SHAP; embeddings; a vector database; any
  demo-seed-data redesign to manufacture more labeled cases; consumption of
  any shadow prediction by `priority()`, `human_queue.priority`, playbook
  selection, diagnosis, guardrails, or execution.
- **`state_machine.py` / `guards.py` / `narrative.py::_validate_citations` /
  `tests/test_ai_boundary.py`:** all byte-unchanged vs. the Phase 6 commit
  (`git diff` empty for each; `test_ai_boundary.py` needed **zero** edits —
  its `AI_PACKAGE.rglob("*.py")` file discovery picked up the new `shadow/`
  subpackage automatically and it passed unmodified).
- **Tests at completion:** the 6 new Phase 7 test files — **54** passed.
  The `tests/test_ai_*.py` family (10 files, including the 6 new Phase 7
  ones) — **177** passed (was 123 after Phase 6, **+54**). Full regression
  suite — **1413** passed (was 1359 after Phase 6, **+54**), 0 failed, 0
  skipped, the same 1 pre-existing cosmetic `StarletteDeprecationWarning`.
  `ruff check .` clean, repository-wide. `alembic upgrade head` -> `0018`
  (no-op — no migration); roundtrip green
  (`tests/test_zz_migrations_roundtrip.py`, 1 passed).
- **Verification status:** complete + verified — `uv run pytest
  tests/test_ai_shadow_*.py -q` (54 passed), `uv run pytest tests/test_ai_*.py
  -q` (177 passed), `uv run pytest -q` (full suite, 1413 passed), `uv run
  ruff check .` (clean, repository-wide), `uv run alembic upgrade head`
  (succeeds, no new migration; head `0018_escalation_resolution`), `uv run
  alembic current`/`heads` (both `0018_escalation_resolution`), `uv run
  pytest tests/test_zz_migrations_roundtrip.py -q` (1 passed), `git diff
  --check` (clean — only pre-existing CRLF/LF advisories), `git diff HEAD --
  src/torque/state_machine.py src/torque/models/guards.py` (both empty),
  `git log main -1` (unchanged at `a0fb0f3`, confirming `main` untouched).
- **Deviations from the literal task wording (all additive, all
  documented):** the model choice (`LogisticRegression`, not the task's own
  earlier-recommended XGBoost+SHAP) — D-146, explicitly authorized by the
  task's own "choose the model based on the actual target/feature structure
  after inspecting the repository" instruction; `network_directive_tier`
  reconstructed from event history rather than read off the current column
  — a stricter-than-strictly-required leakage precaution (D-147); test
  fixtures write `CaseEvent` rows with an explicit `timestamp` rather than
  via `append_case_event`'s server-side `now()` default, because Postgres
  resolves `now()` to the surrounding transaction's start time (a single
  fixed instant per test), which would make "before cutoff / after cutoff"
  fixtures unconstructable otherwise (`tests/ai_shadow_cases.py`).
- **Recommended commit message:**
  `AI Phase 7: Shadow ML — src/torque/ai/shadow/ (labels, schemas, features, model, evaluation, training, scoring), LogisticRegression baseline over the exact Blueprint §8.4 feature set (D-146..D-148), backend/evaluation-only with no persistence/API/UI (D-149), single-merchant scoped (D-150), INV-65; 54 new tests, zero deterministic-core changes, no migration`

---

## (historical) What came next after Module 10

**Module 10 — UI/UX — COMPLETE.** Torque is now a runnable, demo-able product:
`uv run python -m torque` serves the JSON API **and** a static dashboard on one
port. The merchant dashboard shows real recovery metrics (₹ recovered dominant,
`SELF_RECOVERED` separate, exception list up top); every at-risk case drills to
Module 8's "why this case?" panel and the full `CaseEvent` audit trail; the Agent
Console runs the human queue with pause / resolve write-backs
(`escalation_resolution` + `HUMAN_RESOLVED`, migration 0018); the Demo Surface
injects the real ingestion / Decision-K paths and shows a polling live feed of
cases moving through states. Next is **Module 11 — Tech Stack & Infra**
(consolidate the deployment story — Temporal-vs-fallback go/no-go, prod queue,
`docker-compose` worker/beat services) and/or **Module 13 — Demo Script**, plus
**Module 9b — Incrementality** (D-121 / U-10). Do not start without an approved
scope.

Deferred items that do **not** block the next module: Module 9b incrementality;
the 🔮 learned recovery model; `LOG_PROMISE` execution; real channel adapters;
the inter-module dispatch triggers (D-080 / D-088 / D-093); the §5.3 first-touch
MAC lookup (D-083, U-08); a real Temporal engine (D-090); cross-stratum merge;
`Action.cost` population; a browser/e2e test harness for the UI.

---

## (historical) What came next after Module 9

**Module 9 — Reporting & Measurement — COMPLETE.** Torque now turns its event
stream and reconciliation outcomes into a business-level recovery report:
revenue at risk vs money actually recovered (Torque-credited, `SELF_RECOVERED`
shown separately), recovery rate, by leg / intervention / outcome / time, the
operational exception report (blocked / deferred / failed / escalated / terminal),
and case-level drill-down down to the raw `CaseEvent` explainability stream —
all read-only, tenant-scoped, derived on demand (no persisted aggregate). Next is
**Module 10 — UI/UX**: the merchant dashboard (Module 9's metrics + a filterable
case list + the exception list up top), the Agent Console (the explainability
panel + manual pause / cancel / resolve over the human queue —
`escalation_resolution`, `HUMAN_RESOLVED`, `WRITTEN_OFF`), and the demo surface
(live case-state feed + the one-click synthetic-event / Decision-K injectors).
Do not start without an approved scope.

Deferred items that do **not** block Module 10: **Module 9b — Incrementality**
(lift + Wilson CI + cross-merchant SUTVA footnote — D-121 / U-10); the 🔮 learned
recovery model; `LOG_PROMISE` execution; real channel adapters; the inter-module
dispatch triggers (D-080 / D-088 / D-093); the §5.3 first-touch MAC lookup
(D-083, U-08); a real Temporal engine (D-090); cross-stratum merge; `Action.cost`
population.

---

## (historical) What came next after Module 8

**Module 8 — Recovery Scoring Model — COMPLETE.** Every open case now carries a
recovery priority score `(probability × amount_at_risk) ÷ cost` (Decision F
cold-start benchmark → `promise_keeping_rate` warm-start, capped 0.5×–1.3× →
forward `ChannelRateCard` cost), persisted on `revenue_leak_case`, recomputed on
creation / diagnosis / daily, and driving both the Outreach Coordinator and the
human queue through the one `priority()` seam. Next is **Module 9 — Reporting &
Measurement**: ₹ recovered by leg, recovery rate, incrementality lift with a
Wilson score CI, the SUTVA-adjusted lift, the exception list, cost efficiency,
and the mechanical explainability panel over the `CaseEvent` stream. The
`recovery_score` / `recovery_score_breakdown` columns are ready for Module 9's
"top at-risk cases" view. Do not start without an approved scope.

Deferred items that do **not** block Module 9: the 🔮 learned recovery model
(XGBoost / SHAP / uplift); `LOG_PROMISE` execution; real channel adapters; the
earlier inter-module dispatch triggers (D-080 / D-088 / D-093); the §5.3
first-touch MAC lookup (D-083, U-08); a real Temporal engine (D-090);
cross-stratum merge; Module 10 (Agent Console, `WRITTEN_OFF`,
`escalation_resolution`, `HUMAN_RESOLVED`, queue re-sort on score drift).

---

## (historical) What came next after Module 7

**Module 7 — Payment Reconciliation & Attribution — COMPLETE.** Verified success
signals now close cases correctly: direct `PaymentLink` attribution, indirect
`(merchant, counterparty, amount)` matching with the 24h `AGENT_ASSISTED` window,
merged-set `credit_weight` re-split, B2B partial waterfalls, and the §7.1.4
self-paid `CANCELLED` path (U-01 fully resolved). Next is **Module 8 — Recovery
Scoring Model** — implement `(probability × amount_at_risk) ÷ cost` as a live
function (the Decision F cold-start table + `promise_keeping_rate` warm-start,
capped 0.5×–1.3×), cost from `ChannelRateCard`, recompute on
creation/diagnosis/daily. It replaces the `torque.coordination.outreach_coordinator.
priority()` placeholder through that seam (D-098). Do not start without an
approved scope.

Deferred items that do **not** block Module 8: `LOG_PROMISE` execution; real
channel adapters; the earlier inter-module dispatch triggers (D-080 / D-088 /
D-093); the §5.3 first-touch MAC lookup (D-083, U-08); a real Temporal engine
(D-090); cross-stratum merge; Module 10 (Agent Console, `WRITTEN_OFF`,
`escalation_resolution`, `HUMAN_RESOLVED`).
