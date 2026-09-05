# Troubleshooting

Real failure modes encountered while building and rehearsing this demo, and
the actual fix for each — not a generic FAQ.

## `docker compose up -d db` fails / hangs, or `docker ps` shows nothing

Docker Desktop's engine isn't running yet. On Windows this can take up to a
minute after launching the app. Wait, then retry `docker ps`. If it never
comes up, check `sc query com.docker.service` — if `STATE: STOPPED`, start
Docker Desktop manually and wait for its tray icon to settle before retrying.

## `pytest` reports every test skipped with a connection-timeout message

The suite has a session-scoped autouse fixture that checks Postgres
reachability at `TEST_DATABASE_URL` and skips the **entire** run (not a
failure) if it can't connect. Start the database first
(`docker compose up -d db`) and re-run.

## `alembic upgrade head` seems to do nothing

If the schema is already at head, this is correct — `alembic current` will
confirm `0018_escalation_resolution`. If you just recreated the `db`
container (new volume), run it again from a clean state; it will print each
migration as it applies.

## `POST /demo/seed?reset=true` returns `Internal Server Error`

Symptom seen once during development: a `ForeignKeyViolation` on
`scheduled_job` referencing `revenue_leak_case`, followed by
`InFailedSqlTransaction` on every subsequent request. This happens if the
database has leftover rows from a previous run against a *different* schema
version (e.g. you seeded once, then reset the volume without re-running
migrations, or vice versa). Fix: stop the `db` container, remove its volume,
recreate it, run migrations from scratch, then seed:

```bash
docker compose down db
docker volume rm torque_torque_pgdata
docker compose up -d db
uv run alembic upgrade head
curl -X POST "http://127.0.0.1:8000/demo/seed?reset=true"
```

## The "acts" scenario buttons (Payment failure, Checkout abandonment, Cross-leg merge, B2B invoice bundle) return `Internal Server Error`, but the three restraint scenarios work fine

Confirmed cause, seen directly while rehearsing this demo: those four
scenarios call `inject_scenario(..., dispatch=True)`, which enqueues a
Celery task (`dispatch_diagnosis`) onto the Redis broker. If `redis` isn't
running (or its container/network is stale after recreating `db`'s volume),
the enqueue raises and the request 500s — while the three restraint
scenarios (`hard_stop_mac`, `upi_retry_cap`, `nach_ceiling`) succeed, because
they resolve their guardrail block synchronously and never touch Redis.
Fix: `docker compose up -d redis` (or `docker ps -a` to check for a stopped
`torque-redis-1` container — if its network is stale, `docker rm
torque-redis-1` and re-run `docker compose up -d redis` to recreate it
against the current network). Both `db` and `redis` must be up for the full
scenario set — this is already the documented setup step, not a new
requirement, but easy to skip if you only remembered the database.

## "Explain this case" says "AI explanations are not enabled for this deployment"

This is the correct, honest response — `AISettings.enabled` defaults to
`False`. Restart the process with `TORQUE_AI_ENABLED=true` if you want the
AI Assessment to generate. This is not an error to hide; see
[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) beat 3 for how to talk about it either
way.

## A citation chip shows a toast instead of highlighting something

Expected for a `counterparty_relationship:` citation (the authoritative UI
has nowhere to point yet — documented, honest fallback, not a bug) and for
a `promise:` citation in the current seed data (no code path in this build
emits a `PROMISE_CAPTURED` event yet, so there is nothing to anchor to). A
`case_event:` or `case:` citation should always resolve to a real element —
if one of those shows a toast instead, that is a real bug worth filing.

## The Browser-pane screenshot tool shows a narrow column of content next to a large blank area

This is a screenshot-capture artifact of certain preview/automation tooling
under a custom emulated viewport size — it does not reflect the actual
rendered DOM. Confirmed by checking `document.body.getBoundingClientRect()`
and `.view`'s computed width/margins (both correct and centered) and by
re-screenshotting at the tool's native/default size (renders full-width,
correctly). If you see this in a **real** browser window (not an automation
tool), that would be a genuine bug — check `document.querySelectorAll('#view').length`
is `1` and `document.body.scrollWidth === document.body.clientWidth` first.

## A backend code change doesn't seem to take effect

`uv run python -m torque` runs uvicorn **without** `--reload` (see
`src/torque/__main__.py`) — a source edit requires stopping and restarting
the process, not just saving the file. Seen directly while preparing this
demo: a copy-edit to a reporting string stayed stale in the running app
until the process was restarted, even though the file on disk was correct.

## The Live Demo feed doesn't update after clicking a scenario button

It polls every 3 seconds — wait one cycle. If it still doesn't update, check
the Network tab for a failing `GET /reports/{merchant}/activity` call; the
poll silently no-ops on a fetch error rather than surfacing a toast (by
design, so a transient blip doesn't spam the demo with error toasts).

## Docker Desktop won't start inside a sandboxed/CI environment

Some sandboxed dev environments lack the virtualization support Docker
Desktop needs and the engine never comes up no matter how long you wait
(`docker ps` keeps failing with a missing named-pipe error on Windows). In
that case, tests and the demo cannot run in that environment — this is an
environment limitation, not a project bug.
