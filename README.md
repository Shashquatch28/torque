# Torque

Revenue-leakage recovery agent. Closes the leakage loop across four legs —
payment degradation, checkout abandonment, subscription/mandate failure, and
B2B receivables — with one case object and one ledger.

**Source of truth:** [`Torque_Blueprint_v7_FullSystem.md`](Torque_Blueprint_v7_FullSystem.md).
`v4` / `v5` are historical Module-1 revision logs; consult them for rationale
only, never as current spec.

## Status — Milestone 1 (Core Data Model, partial)

This milestone delivers the **case spine, multi-tenancy, and atomic history**
only. There is **no ingestion, diagnosis, playbook, execution, scoring, or
reporting logic** — those are Modules 2–13, built in later milestones.

Delivered:

| Area | What |
|---|---|
| Enums | All Blueprint §4 enums (`torque/enums.py`); Postgres types in migration `0001` |
| Multi-tenancy | `TenantScope` — always injects `merchant_id`; `Counterparty` / static config exempt (R3) |
| Identity & consent | `Merchant`, `Counterparty` (single PII source, `redact_pii()`), `Merchant_Counterparty` (cohort assigned once) |
| Signal log | `Event` (unique `idempotency_key`) + `verify_razorpay_signature()` (raw-body HMAC-SHA256, constant-time) |
| Case spine | `RevenueLeakCase` + typed leg contexts (`PaymentDegradation` / `CheckoutAbandonment` / `SubscriptionFailure`), `B2BInvoice` |
| State machine | Blueprint §4 + Part C edge + confirmed R4 (`PARTIALLY_RECOVERED` non-terminal for B2B only) |
| Event sourcing | `CaseEvent` — append-only (DB trigger + flush guard), 10 locked payload schemas, `atomic()` write primitive |
| Invariant guards | most-restrictive `network_directive`; Module-7-only `recovery_type` / `recovered_amount`; typed `context` on every flush |

Not in this milestone (Milestone 2/3): retry-budget entities, `MacCodeRegistry`,
`SystemicEvent`, `Playbook`/`PlaybookRun`/`Action`/`ActionCase`, `PaymentLink`,
`PromiseToPay`, `MerchantWhatsAppTemplate`, `ChannelRateCard`, the webhook HTTP
endpoint, FastAPI.

## Stack

Python ≥ 3.11 · SQLAlchemy 2.0 · Alembic · Pydantic v2 · PostgreSQL 16.
(FastAPI + Celery/Redis + Temporal enter with Module 2.)

## Setup

```bash
# 1. infrastructure (Postgres + Redis)
docker compose up -d db

# 2. environment
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                # adjust credentials if needed

# 3. schema
alembic upgrade head

# 4. tests  (creates/uses the `torque_test` database)
pytest
```

The docker-compose `db` service publishes on host port **5442** (not 5432) so it
never collides with a local Postgres install. `TEST_DATABASE_URL` (default
`postgresql+psycopg://postgres:postgres@localhost:5442/torque_test`) controls
where the suite runs; it drops and recreates the `public` schema there on every
run and applies migrations.

## Layout

```
src/torque/
  enums.py            Blueprint §4 enum reference
  config.py           Settings + PolicyConfig (tunable windows, consumed later)
  exceptions.py       domain errors
  db/                 Base, session factory, TenantScope
  models/             ORM models + guards.py (flush-time invariant enforcement)
  contexts/           typed leg-context models + validate_context
  events/             CaseEvent payload schemas + append_case_event + atomic
  security/           razorpay_signature (pure HMAC helper)
  state_machine.py    status transitions, apply_network_directive, sync_control_group
migrations/           Alembic (0001 enums → 0005 case_event)
tests/                Postgres-backed; skips cleanly if no server
```

## Version control

This repo is not yet under git. Nothing here is staged or committed — the
maintainer handles all VCS operations.
