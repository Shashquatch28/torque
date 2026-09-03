"""Module 5 — Execution & Orchestration (Blueprint §5).

Executes a version-pinned `PlaybookRun`'s graph at runtime: resolve the current
`active_step_id`, run the §5.2 guardrails, execute the action (§5.4 stubs), record
the outcome + `STEP_TRANSITIONED` audit atomically, advance the pointer, and
reschedule — driven by the §5.6 Postgres-polling timer (chosen over Temporal for
the build window, D-090).

Public surface:
* `schedule_run(session, run_id=...)` — arm a run's first timer.
* `execute_due_jobs(session, leg_types=...)` — one poll pass.
* `execute_due_job(session, job)` — execute one claimed job (the workflow tick).
* `StepResult` — the tick outcome enum.
"""

from __future__ import annotations

from torque.execution.runner import StepResult, execute_due_job
from torque.execution.scheduler import (
    OTHER_LEGS,
    PAYMENT_LEGS,
    claim_due_jobs,
    execute_due_jobs,
    schedule_run,
)

__all__ = [
    "OTHER_LEGS",
    "PAYMENT_LEGS",
    "StepResult",
    "claim_due_jobs",
    "execute_due_job",
    "execute_due_jobs",
    "schedule_run",
]
