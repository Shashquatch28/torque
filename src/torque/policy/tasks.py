"""Celery task for Module 4 — Policy & Playbook Engine.

Selecting a playbook and instantiating a run is short-lived, stateless work — the
same class as Module 2 ingestion and Module 3 diagnosis, and explicitly NOT the
durable execution workflow (durable state is Module 5's `scheduled_job` table,
D-090). Thin: open one `session_scope()`, delegate to `activate_case`, return a
short string.

**Module 12a (D-137, resolves D-088/D-093).** The Module 3 → Module 4 automatic
*enqueue* is now wired — see `torque.diagnosis.tasks._dispatch_activation`, which
calls this task. This task in turn closes the Module 4 → Module 5 hand-off: when
`activate_case` returns `RUN_CREATED`, the just-created `PlaybookRun` is armed
via `torque.execution.scheduler.schedule_run` — **inside the same transaction**
as `activate_case` (unlike the two Celery-task hops above, this is a plain
function call, not a dispatch, so "run created" and "run's first timer armed"
commit atomically together; a rollback of one rolls back both). Arming a
`ScheduledJob` row is all "scheduling execution" means here — the existing
Postgres-polling beat pollers (`torque.execution.tasks`, unchanged) are what
actually execute it, on their existing 10 s / 60 s schedule (D-090, not
reopened). `ESCALATED_NO_PLAYBOOK`, `ESCALATED_DISABLED`, and `NOOP` schedule
nothing — an escalated case has no run to schedule.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from torque.db.session import session_scope
from torque.enums import PlaybookRunStatus
from torque.ingestion.celery_app import celery_app
from torque.models import PlaybookRun
from torque.policy.engine import ActivationOutcome, activate_case

_session_scope = session_scope


@celery_app.task(name="torque.policy.activate_case", ignore_result=True)
def activate_case_task(case_id: str) -> str:
    """Activate one diagnosed case (Blueprint §4). Idempotent under redelivery."""
    with _session_scope() as session:
        outcome = activate_case(session, case_id=uuid.UUID(str(case_id)))
        if outcome is ActivationOutcome.RUN_CREATED:
            from torque.execution.scheduler import schedule_run

            run = session.scalars(
                select(PlaybookRun)
                .where(PlaybookRun.case_id == uuid.UUID(str(case_id)))
                .where(PlaybookRun.status == PlaybookRunStatus.RUNNING)
            ).first()
            if run is not None:  # pragma: no branch - activate_case just created it
                schedule_run(session, run_id=run.run_id)
    return outcome.name
