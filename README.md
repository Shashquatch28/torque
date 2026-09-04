# Torque

Revenue-leakage recovery agent. Closes the leakage loop across four legs —
payment degradation, checkout abandonment, subscription/mandate failure, and
B2B receivables — with one case object and one ledger.

**Source of truth:** [`Torque_Blueprint_v7_FullSystem.md`](Torque_Blueprint_v7_FullSystem.md).
`v4` / `v5` are historical Module-1 revision logs; consult them for rationale
only, never as current spec.

## Status

Modules **1–11 + 9b complete** (Module 9b uncommitted at time of writing). The
authoritative, always-current snapshot — what is built, the migration head, the
test count, unresolved items — is
[`documentation/ai-memory/CURRENT_STATE.md`](documentation/ai-memory/CURRENT_STATE.md).
The rest of `documentation/ai-memory/` is the derived project memory
(`ARCHITECTURE.md`, `DECISIONS.md`, `MILESTONES.md`, `INVARIANTS.md`,
`DEFERRED.md`, `UNRESOLVED.md`).

Highlights: shared case spine + append-only `CaseEvent` ledger, application-layer
multi-tenancy, four-leg signal ingestion (Celery + Redis broker), rule-based
diagnosis, the playbook catalog + version-pinned runs, the **Postgres-polling**
execution driver (`scheduled_job` + stratified Celery-beat pollers — Temporal was
the alternative; D-090), the compliance / cross-leg guardrail engine + human
queue, payment reconciliation, `(probability × amount) ÷ cost` recovery scoring,
the read-only reporting API — **descriptive** (₹ recovered, recovery rate, by
leg/intervention/time, exceptions) **and, since Module 9b, causal**
(treatment-vs-control incremental lift with a Wilson/Newcombe confidence
interval and the Blueprint §6 SUTVA cross-merchant adjustment, shown alongside
the headline, never instead of it) — a static SPA dashboard + Agent Console +
demo surface on one port, and (Module 11) a reproducible `docker-compose`
runtime.

## Stack

Python ≥ 3.11 · SQLAlchemy 2.0 · Alembic · Pydantic v2 · FastAPI + uvicorn ·
Celery + Redis (**broker only**, no result backend) · PostgreSQL 16 · `uv` ·
pytest · ruff. Containerised with one `Dockerfile` (`uv`-locked). **No Node. No
Temporal** (Postgres-polling is the durable execution driver — D-090).

## Runtime topology

Five processes: **PostgreSQL** (the single durable source of truth) · **Redis**
(Celery broker transport only) · **api** (`python -m torque` — FastAPI + the
static UI, one port) · **worker** (`celery … worker` — runs every `torque.*`
task) · **beat** (`celery … beat` — the repeatable-timer trigger: systemic 60s,
execution poll 10s/60s, daily recovery-score recompute).

## Setup — host dev loop

```bash
# 1. infrastructure
docker compose up -d db redis        # Postgres :5442, Redis :6389 (offset ports)

# 2. environment
uv sync                              # or: python -m venv .venv && pip install -e ".[dev]"
cp .env.example .env                 # fill secrets only if you need the webhook / injection paths

# 3. schema
uv run alembic upgrade head          # -> 0018

# 4a. run the app (API + UI on http://127.0.0.1:8000)
uv run python -m torque
#    (Celery, if needed:  uv run celery -A torque.ingestion.celery_app:celery_app worker
#                         uv run celery -A torque.ingestion.celery_app:celery_app beat)

# 4b. tests  (creates/uses the `torque_test` database)
uv run pytest
uv run ruff check .
```

## Run the full stack in containers

```bash
cp .env.example .env
docker compose --profile full up --build
```

Brings up `db + redis + migrate + api + worker + beat`. `migrate` runs
`alembic upgrade head` once; `api` waits for it, then serves
`http://127.0.0.1:8000` (`/` → `/ui/`, `/health`, `/health/ready`). A bare
`docker compose up` (no `--profile full`) still starts only `db` + `redis`, so
the host loop above is unaffected.

The `db` / `redis` services publish on host ports **5442** / **6389** (not the
standard 5432 / 6379) so they never collide with a local install.
`TEST_DATABASE_URL` (default
`postgresql+psycopg://postgres:postgres@localhost:5442/torque_test`) controls
where the suite runs; it drops/recreates the `public` schema there and applies
migrations on every run.

## Layout

```
src/torque/
  enums.py            Blueprint §4 enum reference
  config.py           Settings (env-driven) + PolicyConfig (tunable windows/thresholds)
  exceptions.py       domain errors
  db/                 Base, session factory, TenantScope
  models/             ORM models + guards.py (flush-time invariant enforcement)
  contexts/           typed leg-context models + validate_context
  events/             CaseEvent payload schemas + append_case_event + atomic
  state_machine.py    status transitions, apply_network_directive, sync_control_group
  security/           razorpay_signature (pure HMAC helper)
  ingestion/ diagnosis/ policy/ execution/ coordination/ reconciliation/
  scoring/ reporting/ agent_console/ demo/     the module 2–10 packages
  api/                FastAPI app, routers (webhooks, reporting, agent console,
                      demo, health), static UI mount
Dockerfile           one reusable image (api / worker / beat)
docker-compose.yml    db + redis (+ migrate/api/worker/beat behind `--profile full`)
migrations/           Alembic (0001 … 0018)
tests/                Postgres-backed; skips cleanly if no server
```

## Version control

The **maintainer performs all Git operations.** Contributors (human or agent)
never `commit`, `push`, or otherwise write to Git — see
[`documentation/ai-memory/CONTINUATION_PROTOCOL.md`](documentation/ai-memory/CONTINUATION_PROTOCOL.md).
