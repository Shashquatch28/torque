"""The Postgres-polling driver — Blueprint §5.6 (chosen over Temporal, D-090).

`schedule_run` arms a run's first timer (its entry step's computed fire time).
`claim_due_jobs` is the poller's claim query — `fire_at <= now`, filtered to the
caller's leg stratum, `ORDER BY fire_at … FOR UPDATE SKIP LOCKED`: two workers
never claim the same row, so step execution is exactly-once without any external
lock (item 23). `execute_due_jobs` claims and runs a batch in one pass.

Two strata (§5.6): a 10 s poller for `PAYMENT_DEGRADATION` (live customer-session
recovery window) and a 60 s poller for the other three legs (multi-day timelines
make the latency immaterial). The Celery beat schedule wiring is in
`torque.execution.tasks`.

Wiring `schedule_run` to fire automatically when Module 4 creates a run is the
Module 4 → Module 5 hand-off trigger, deferred to the orchestration layer for the
same reason as the earlier inter-module dispatches (D-093) — the engine + poller
are ready and independently invocable; nothing enqueues them by itself yet.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.enums import LegType
from torque.execution import timing
from torque.execution.runner import StepResult, execute_due_job
from torque.models import Merchant, Playbook, PlaybookRun, RevenueLeakCase, ScheduledJob
from torque.policy import traversal
from torque.policy.engine import resolve_effective_stopping_rules
from torque.policy.payday import effective_timing_adjustment

# §5.6 poller strata.
PAYMENT_LEGS: tuple[LegType, ...] = (LegType.PAYMENT_DEGRADATION,)
OTHER_LEGS: tuple[LegType, ...] = (
    LegType.CHECKOUT_ABANDONMENT,
    LegType.SUBSCRIPTION_FAILURE,
    LegType.B2B_RECEIVABLE,
)


def schedule_run(
    session: Session, *, run_id: uuid.UUID, now: datetime | None = None
) -> ScheduledJob | None:
    """Arm the first timer for a freshly-created `RUNNING` run, at its entry step's
    computed fire time. Idempotent: `UNIQUE(run_id)` means a second call (or a run
    that already has a pending timer) is a no-op returning the existing job."""
    now = now or datetime.now(UTC)
    run = session.get(PlaybookRun, run_id)
    if run is None:
        return None
    existing = session.scalars(
        select(ScheduledJob).where(ScheduledJob.run_id == run_id)
    ).first()
    if existing is not None:
        return existing

    case = session.get(RevenueLeakCase, run.case_id)
    pinned = session.get(Playbook, (run.playbook_id, run.playbook_version))
    entry_node = traversal.node(pinned.steps_graph, run.active_step_id)
    rules = resolve_effective_stopping_rules(session, run)
    merchant = session.get(Merchant, run.merchant_id)
    payday = effective_timing_adjustment(case, merchant) if merchant is not None else None
    fire_at = timing.compute_fire_time(
        previous_completion=run.created_at or now,
        timing_offset_hours=float(entry_node.get("timing_offset_hours", 0)),
        allowed_start=rules.allowed_hours.start,
        allowed_end=rules.allowed_hours.end,
        payday_adjustment=payday,
    )
    job = ScheduledJob(
        run_id=run.run_id,
        case_id=run.case_id,
        fire_at=fire_at,
        leg_type=LegType(case.leg_type),
    )
    TenantScope(session, run.merchant_id).add(job)
    session.flush()
    return job


def claim_due_jobs(
    session: Session,
    *,
    leg_types: Sequence[LegType],
    now: datetime | None = None,
    limit: int = 100,
) -> list[ScheduledJob]:
    """Claim up to `limit` due jobs for the given legs, skip-locking rows another
    worker already holds (§5.6). The caller executes and commits them."""
    now = now or datetime.now(UTC)
    return list(
        session.scalars(
            select(ScheduledJob)
            .where(ScheduledJob.fire_at <= now)
            .where(ScheduledJob.leg_type.in_(tuple(leg_types)))
            .order_by(ScheduledJob.fire_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )


def execute_due_jobs(
    session: Session,
    *,
    leg_types: Sequence[LegType],
    now: datetime | None = None,
    limit: int = 100,
) -> list[StepResult]:
    """One poll pass: claim due jobs for `leg_types` and execute each. Returns the
    per-job results. The caller owns the transaction."""
    now = now or datetime.now(UTC)
    results: list[StepResult] = []
    for job in claim_due_jobs(session, leg_types=leg_types, now=now, limit=limit):
        results.append(execute_due_job(session, job, now=now))
    return results
