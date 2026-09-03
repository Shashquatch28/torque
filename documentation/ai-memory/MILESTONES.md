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

## What comes next

**Module 6 — Compliance & Cross-Leg Guardrail Engine — COMPLETE.** The
`GuardrailEngine` facade is the one interface Module 5 consults; the Outreach
Coordinator (4h cross-leg quiet period, live merge, defer, open-conversation),
the full WhatsApp gate, the §6.3 escalation ceiling, and the persistent human
queue are all live. Next is **Module 7 — Payment Reconciliation & Attribution**
(match `payment.captured` / `subscription.charged` / `payment_link.paid` to open
cases; `AGENT_ASSISTED` vs `SELF_RECOVERED`; `credit_weight` re-split; case
closure + `PAYMENT_RECONCILED`; the `DETECTED/DIAGNOSING → CANCELLED` edges,
U-01). Do not start it without an approved scope.

Deferred items that do **not** block Module 7: Module 8 scoring (the `priority()`
seam awaits it); `LOG_PROMISE` execution; real channel adapters; the earlier
inter-module dispatch triggers (D-080 / D-088 / D-093); the §5.3 first-touch MAC
lookup (D-083, U-08); a real Temporal engine (D-090); cross-stratum merge.
