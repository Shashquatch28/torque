"""The Celery application for Module 2 inbound delayed work.

Redis is the broker; there is **no result backend** — Postgres is the source of
truth for every ingestion outcome (a written/updated `Event.processed`, a
`RevenueLeakCase`, a `superseded_by_case_id`, a `CardRetryBudget`). Task
functions return a small string purely for logs/eager-mode assertions.

Run a worker in dev with:

    uv run celery -A torque.ingestion.celery_app:celery_app worker --loglevel=info

Construction does not open a broker connection; `apply_async` does.
`Settings.celery_task_always_eager` (set only by the test harness) makes tasks
run inline with no broker or worker.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from torque.config import get_settings

_settings = get_settings()

celery_app = Celery("torque", broker=_settings.redis_url)
celery_app.conf.update(
    task_ignore_result=True,
    result_backend=None,
    broker_connection_retry_on_startup=True,
    task_always_eager=_settings.celery_task_always_eager,
    task_eager_propagates=_settings.celery_task_always_eager,
    timezone="UTC",
)
celery_app.autodiscover_tasks(
    [
        "torque.ingestion",
        "torque.diagnosis",
        "torque.policy",
        "torque.execution",
        "torque.reconciliation",
        "torque.scoring",
    ]
)

# Repeatable beat jobs. §2.5 systemic detection (60s), plus the Module 5 §5.6
# stratified execution pollers: 10s for PAYMENT_DEGRADATION's live-session window,
# 60s for the other three legs' multi-day timelines, plus the Module 8 §8.5
# item-3 daily recovery-score recompute for every open case.
# Run the scheduler in dev with:
#   uv run celery -A torque.ingestion.celery_app:celery_app beat
celery_app.conf.beat_schedule = {
    "systemic-detection": {
        "task": "torque.ingestion.detect_systemic",
        "schedule": 60.0,
    },
    "execution-poll-payment": {
        "task": "torque.execution.poll_payment_jobs",
        "schedule": 10.0,
    },
    "execution-poll-other": {
        "task": "torque.execution.poll_other_jobs",
        "schedule": 60.0,
    },
    "recovery-score-daily-recompute": {
        "task": "torque.scoring.recompute_open_case_scores",
        "schedule": crontab(hour=2, minute=0),
    },
}

# Import the task modules so the tasks register even without autodiscovery
# (autodiscovery only fires for installed apps in some run modes). Each module's
# tasks live in its own package; they are registered here the same way.
from torque.diagnosis import tasks as _diagnosis_tasks  # noqa: E402,F401
from torque.execution import tasks as _execution_tasks  # noqa: E402,F401
from torque.ingestion import tasks as _tasks  # noqa: E402,F401
from torque.policy import tasks as _policy_tasks  # noqa: E402,F401
from torque.reconciliation import tasks as _reconciliation_tasks  # noqa: E402,F401
from torque.scoring import tasks as _scoring_tasks  # noqa: E402,F401
