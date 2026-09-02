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
celery_app.autodiscover_tasks(["torque.ingestion"])

# Blueprint §2.5 (Milestone 7c): the systemic-detection job runs every 60s.
# Run the scheduler in dev with:
#   uv run celery -A torque.ingestion.celery_app:celery_app beat
celery_app.conf.beat_schedule = {
    "systemic-detection": {
        "task": "torque.ingestion.detect_systemic",
        "schedule": 60.0,
    },
}

# Import the task module so the tasks register even without autodiscovery
# (autodiscovery only fires for installed apps in some run modes).
from torque.ingestion import tasks as _tasks  # noqa: E402,F401
