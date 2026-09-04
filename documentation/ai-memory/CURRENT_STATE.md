# CURRENT STATE — read this first

**Last updated:** 2026-09-04, after the **Module 11 — Tech Stack & Infra** run
(**uncommitted**, on top of committed Modules 1–10).
**Reconstructed from:** committed Modules 1–10 (HEAD `7b89e36`) + the uncommitted
Module 11 changes + `Torque_Blueprint_v7_FullSystem.md`.
**This file is derived documentation, not authoritative.** The repo and blueprint win.

---

## What Torque is

A revenue-leakage recovery agent closing the loop across four funnel legs —
**payment degradation, checkout abandonment, subscription/mandate failure, B2B
receivables** — with **one shared case object and one shared event ledger**. It
diagnoses root cause, runs a bounded recovery playbook under hard compliance
guardrails, reconciles incoming payments back to the leaking case, scores every
open case by its economic recovery opportunity, reports the business outcome,
presents all of it as a runnable product (dashboard + agent console + live demo
on one port), and — new in Module 11 — **ships that runtime as a reproducible,
free-tier `docker-compose` stack**. Full vision: `PROJECT_CONTEXT.md` §1. Spec:
`Torque_Blueprint_v7_FullSystem.md`. Product-pitch knowledge base:
`learning_log.md` (root).

## Where we are

**Modules 1–8 — COMPLETE & committed** (`8fbd97b` = Module 8).
**Modules 9 + 10 — COMPLETE & committed** (`7b89e36`, one squashed commit —
descriptive reporting + Agent Console UI/UX).
**Module 11 — Tech Stack & Infra — COMPLETE** (this run, **uncommitted**).

| Module 11 capability | Behaviour |
|---|---|
| Reproducible runtime (D-128/129/130) | One reusable **`Dockerfile`** (`python:3.11-slim`, `uv sync --frozen` from `uv.lock`, `--no-dev`, non-root `USER torque`) builds the API, the Celery worker, and Celery beat. **`docker-compose.yml`** now defines the whole runtime: `db` + `redis` (unchanged, **profile-free**) and, behind **`profiles: ["full"]`**, `migrate` (one-shot `alembic upgrade head`), `api` (`8000:8000`, `TORQUE_API_HOST=0.0.0.0`), `worker`, `beat`. `docker compose --profile full up` = the five-process runtime; a bare `docker compose up` = infra only, so the host loop (`… up -d db redis` + `uv run python -m torque`) is untouched. |
| Config coherence (D-131) | **`Settings.api_host` / `api_port`** added (alias `TORQUE_API_HOST` / `TORQUE_API_PORT`, defaults `127.0.0.1:8000`) — the one value `__main__` read straight from `os.environ` now flows through `Settings`. **`.env.example` rewritten** to document every `Settings` field + every `PolicyConfig` field (prefix `TORQUE_POLICY_`), with defaults, comments, compose-network alternates, and **no secrets** (parity + fail-closed defaults are test-enforced). |
| Minimal operability (D-132) | **`GET /health/ready`** — `SELECT 1` on Postgres + a 1 s Redis `PING`; `200 {"status":"ready","checks":{…}}` or `503` naming the failed component. **`GET /health` unchanged** (still `{"status":"ok"}`). Both now live in `torque.api.health` (`health_router`); `create_app()` is pure wiring. No metrics / tracing / observability stack. |
| Backend language (D-126) | **Python**, made explicit — resolves Blueprint Part D item 2 / U-05 (decided-by-implementation since M1). |
| Durable execution (D-090 / D-127) | **Unchanged.** `scheduled_job` + `execute_due_job` (Postgres-polling, `FOR UPDATE SKIP LOCKED`) stay the durable `PlaybookRun` driver. Redis stays **broker-only** (`result_backend=None`, no persistence, no volume). **No Temporal** — documented only as a future driver swap. |
| Migration | **none.** `alembic head` stays `0018_escalation_resolution`. |
| State machine / guards | **`state_machine.py` and `guards.py` byte-unchanged vs HEAD.** Module 11 adds no transition, no guard, no guarded field. |

**Modules 12–13 (Build Roadmap, Demo Script) and Module 9b (Incrementality) not started.**

## Verified facts (checked this session against the repo)

| Fact | Value |
|---|---|
| Git HEAD (`main`) | **`7b89e36`** "Module 9–10: descriptive reporting + Agent Console UI/UX". Module 11 changes sit **uncommitted** on top. |
| Working tree (Module 11) | **New:** `Dockerfile`, `.dockerignore`, `src/torque/api/health.py`, `tests/test_infra_compose.py`, `tests/test_infra_celery.py`, `tests/test_config_env_parity.py`, `tests/test_health_endpoints.py`. **Modified:** `docker-compose.yml`, `.env.example`, `src/torque/config.py`, `src/torque/__main__.py`, `src/torque/api/app.py`, plus the six `documentation/ai-memory/*` files. |
| Alembic head | **`0018_escalation_resolution`** — Module 11 adds no migration. |
| Test suite | **1144 passed** (`uv run pytest -q`), 0 fail / 0 skip. 1 pre-existing cosmetic `StarletteDeprecationWarning`. Was 1109 at `7b89e36`; `+35` (14 compose + 9 celery + 6 config-parity + 6 health). |
| Lint | `uv run ruff check .` → clean. No frontend lint/build (D-122). |
| Migration roundtrip | green (`tests/test_zz_migrations_roundtrip.py`, up→down→up incl. 0018). |
| `src/torque/state_machine.py` | **`git diff HEAD --` empty** — byte-unchanged (unchanged since M1). |
| `src/torque/models/guards.py` | **`git diff HEAD --` empty** — the `human_resolution_writer` addition (D-123) is committed at `7b89e36`; Module 11 does not touch it. |
| Stack | Python 3.11, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI + StaticFiles, Celery + Redis (broker only) + beat, PostgreSQL 16, `uv`, pytest, ruff. **+ `Dockerfile` / `.dockerignore` / full `docker-compose`.** **No Node.** No Temporal. |
| DB / infra | Postgres host **5442**; Redis host **6389**; API host **8000** (compose `full` profile). **25 tables** (unchanged). |

## What is implemented (new in Module 11)

- **`Dockerfile` + `.dockerignore`** — one reusable image for api / worker / beat.
- **`docker-compose.yml`** — `db` + `redis` (profile-free) + `migrate` + `api` +
  `worker` + `beat` (profile `full`); one YAML anchor for the shared build /
  image / compose-network env; explicit `depends_on` health/completion gates.
- **`torque.api.health`** — `GET /health` (moved, unchanged) + `GET /health/ready`
  (`check_database` / `check_redis`, 200/503).
- **`Settings.api_host` / `api_port`**; `__main__` reads them via `Settings`.
- **`.env.example`** — full `Settings` + `PolicyConfig` surface, no secrets.
- Four Docker-free infra/config tests.

Full breakdown: `ARCHITECTURE.md` §8K.

## How to run the product locally

**Host dev loop (unchanged):**

```
docker compose up -d db redis              # Postgres :5442, Redis :6389
uv run alembic upgrade head                # → 0018
uv run python -m torque                    # API + UI on http://127.0.0.1:8000
curl -X POST http://127.0.0.1:8000/demo/seed        # deterministic acc_demo dataset
# open http://127.0.0.1:8000/  → redirects to /ui/
```

**Full containerised runtime (new — Module 11):**

```
cp .env.example .env                       # fill secrets if you need the webhook / injection paths
docker compose --profile full up --build   # db + redis + migrate + api + worker + beat
# migrate runs `alembic upgrade head` once; api waits for it, then serves :8000
curl http://127.0.0.1:8000/health/ready    # {"status":"ready","checks":{"database":"ok","redis":"ok"}}
curl -X POST http://127.0.0.1:8000/demo/seed
# open http://127.0.0.1:8000/
```

## Next milestone

**Module 12 — Build Roadmap** (phase → calendar plan; needs Part D item 3 — build
window length) and/or **Module 13 — Demo Script** (needs Part D item 4 — judging
rubric), plus **Module 9b — Incrementality** (D-121 / U-10 — lift + Wilson CI +
SUTVA). Do not start without an approved scope.

## Never-violate rules (short form — full list in CONTINUATION_PROTOCOL.md)

1. **No Git write operations.** The maintainer does all VCS.
2. **The blueprint is law.** Deviations only if proposed, justified, approved,
   documented in code + `DECISIONS.md`. (Module 11: no deviation — the
   blueprint's Module 11 is a consolidation table; D-126/127 confirm the
   already-made choices, D-090 stays IN FORCE.)
3. **One module = one implementation run = one audit.**
4. **Do not implement `DEFERRED.md` work as a side effect.**
5. **Do not resolve `UNRESOLVED.md` questions unilaterally.** (Module 11 resolved
   only U-05's Part D item 2 — the maintainer's locked decision — and left every
   other U-item untouched.)
6. `state_machine.py` / `guards.py` are load-bearing. **Module 11 touched
   neither** (`git diff HEAD --` empty for both). `state_machine.py` unchanged
   since M1; `guards.py` last changed by Module 10 (`human_resolution_writer`,
   committed at `7b89e36`).
7. Every run verifies: `pytest`, `ruff`, migration roundtrip, `git diff HEAD` of
   `state_machine.py` **and** `guards.py`.

## Unresolved decisions / questions right now

- **U-01 / U-02 / U-07** — RESOLVED.
- **U-05** — Part D item 1 (synthetic injection) and **item 2 (backend = Python,
  D-126)** RESOLVED. Items 3–4 (build window, judging rubric) open — Modules
  12–13.
- **U-03 / U-04 / U-06 / U-08** — open (MAC precedence, systemic N/M numbers,
  Part D residue, issuer extraction). None constrain Modules 12–13.
- **U-09** — Module 8 calibration values are stated defaults. Not blocking.
- **U-10** — incrementality / causal measurement deferred to "Module 9b". Not
  blocking.
- **U-11** — Agent Console `escalation_resolution` vocabulary / pause target are
  Module-10 choices the blueprint underspecifies (D-123 / D-124). Not blocking.
- **D-090 (Postgres-polling over Temporal)** — **IN FORCE.** Module 11 reaffirmed
  it (D-127); do not reopen.

## Known contradictions / caveats

- **`README.md` refreshed for Module 11** (Setup / Stack / run paths). The
  historical "Milestone 1" framing higher up is superseded by this file — trust
  `CURRENT_STATE.md` / the code.
- **Module 11 is uncommitted** on top of committed Modules 1–10 (`7b89e36`).
  Every "verified fact" (1144 tests) reflects the working tree.
- **Redis is broker-only** — `result_backend=None`, no persistence, no
  `docker-compose` volume. No durable application state is ever in Redis.
- **`docker compose --profile full up` needs a `.env` file** (compose `env_file:
  .env`); `cp .env.example .env` first. The compose `environment:` block still
  injects the critical compose-network `DATABASE_URL` / `REDIS_URL` /
  `TORQUE_API_HOST` overrides regardless.
- **`beat` writes its schedule bookkeeping to `/tmp/celerybeat-schedule`** (the
  container runs non-root with a read-only working dir). It holds no durable
  state — the source of truth for execution timers is `scheduled_job`.
- **The executor is still a stub (§5.4).** Torque still fires no real messages /
  charges; execution is not auto-triggered (D-080/D-088/D-093). Module 11 changed
  nothing about this.
- **No Temporal.** D-090 / D-127 — the Postgres-polling driver is the durable
  execution mechanism; Temporal is a future driver swap only.
- **No browser/e2e harness** (D-122); a Dockerised `--profile full` smoke test is
  a manual maintainer step, not in the pytest suite (the infra tests assert the
  config/command contract without Docker).
- Module 1–10 caveats still stand (UI computes nothing; "Cancel" = `WRITTEN_OFF`;
  demo `reset` disables the `case_event` trigger for its scoped wipe; large
  `recovery_score` values for unpriced open cases; pre-existing suite flakiness
  under load).

## What to do next (for the agent reading this)

Follow `CONTINUATION_PROTOCOL.md`: verify this snapshot against the live repo
(`git log`, `git status`, `alembic heads/current`, `pytest`, `ruff`,
`git diff HEAD -- src/torque/state_machine.py` and `-- src/torque/models/guards.py`
— **both expected empty**), report any drift, then — once the maintainer has
committed Module 11 — propose **Module 12 — Build Roadmap** or **Module 13 —
Demo Script** (or **Module 9b — Incrementality**) as one continuous scope.
