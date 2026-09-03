"""Celery-beat pollers for the §5.6 Postgres-polling execution driver.

Two stratified repeatable jobs (§5.6): a 10 s poller for `PAYMENT_DEGRADATION`
(the live customer-session recovery window) and a 60 s poller for the other three
legs. Each pass opens one `session_scope()`, claims due `ScheduledJob`s
(`FOR UPDATE SKIP LOCKED`), executes them, and commits — so the claim lock is held
only for the work, and a crash rolls the pass back for the next tick.

Celery/BullMQ is used here strictly as the *repeatable-timer trigger* (§5.5's
"short-lived, stateless" role); the durable business state lives entirely in
Postgres (`scheduled_job` + the case/run/event tables) — Celery task state is
never the source of truth. `_session_scope` is module-level indirection so tests
can bind the poller to the harness session.
"""

from __future__ import annotations

from datetime import UTC, datetime

from torque.db.session import session_scope
from torque.execution.scheduler import OTHER_LEGS, PAYMENT_LEGS, execute_due_jobs
from torque.ingestion.celery_app import celery_app

_session_scope = session_scope


@celery_app.task(name="torque.execution.poll_payment_jobs", ignore_result=True)
def poll_payment_jobs_task() -> str:
    """§5.6 10 s stratum — `PAYMENT_DEGRADATION` live-session recovery."""
    with _session_scope() as session:
        results = execute_due_jobs(session, leg_types=PAYMENT_LEGS, now=datetime.now(UTC))
    return f"payment:{len(results)}"


@celery_app.task(name="torque.execution.poll_other_jobs", ignore_result=True)
def poll_other_jobs_task() -> str:
    """§5.6 60 s stratum — checkout / subscription / B2B multi-day timelines."""
    with _session_scope() as session:
        results = execute_due_jobs(session, leg_types=OTHER_LEGS, now=datetime.now(UTC))
    return f"other:{len(results)}"
