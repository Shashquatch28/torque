"""Module 11 — the Celery application / queue contract.

The Celery app loads, Redis is broker-only (no result backend), every torque.*
task is registered, the §5.6 execution polling schedule is intact (10 s payment
/ 60 s other legs), and `scheduled_job` remains the durable execution source.
No Temporal.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from celery.schedules import crontab

from torque.ingestion.celery_app import celery_app

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TASKS = {
    "torque.ingestion.resolve_buffered_event",
    "torque.ingestion.resolve_subscription_buffered_event",
    "torque.ingestion.create_checkout_case",
    "torque.ingestion.ingest_invoice",
    "torque.ingestion.detect_systemic",
    "torque.diagnosis.diagnose_case",
    "torque.policy.activate_case",
    "torque.execution.poll_payment_jobs",
    "torque.execution.poll_other_jobs",
    "torque.reconciliation.reconcile_event",
    "torque.scoring.recompute_recovery_score",
    "torque.scoring.recompute_open_case_scores",
}


def test_celery_app_loads_with_redis_broker_only() -> None:
    assert celery_app.main == "torque"
    assert str(celery_app.conf.broker_url).startswith("redis://")
    # Redis is broker transport ONLY — no result backend, results ignored.
    assert not celery_app.conf.result_backend
    assert celery_app.conf.task_ignore_result is True
    assert celery_app.conf.timezone == "UTC"


def test_all_torque_tasks_are_registered() -> None:
    registered = set(celery_app.tasks)
    missing = EXPECTED_TASKS - registered
    assert not missing, f"unregistered tasks: {missing}"


def test_beat_schedule_has_the_execution_pollers() -> None:
    bs = celery_app.conf.beat_schedule
    assert {
        "systemic-detection",
        "execution-poll-payment",
        "execution-poll-other",
        "recovery-score-daily-recompute",
    } <= set(bs)


def test_payment_degradation_polling_is_10_seconds() -> None:
    entry = celery_app.conf.beat_schedule["execution-poll-payment"]
    assert entry["task"] == "torque.execution.poll_payment_jobs"
    assert entry["schedule"] == 10.0


def test_other_legs_polling_is_60_seconds() -> None:
    entry = celery_app.conf.beat_schedule["execution-poll-other"]
    assert entry["task"] == "torque.execution.poll_other_jobs"
    assert entry["schedule"] == 60.0


def test_systemic_detection_stays_60_seconds() -> None:
    assert celery_app.conf.beat_schedule["systemic-detection"]["schedule"] == 60.0


def test_daily_recovery_score_recompute_schedule() -> None:
    sched = celery_app.conf.beat_schedule["recovery-score-daily-recompute"]["schedule"]
    assert isinstance(sched, crontab)
    assert sched.hour == {2}
    assert sched.minute == {0}


def test_scheduled_job_remains_the_durable_execution_source() -> None:
    from torque.models import ScheduledJob

    cols = set(ScheduledJob.__table__.columns.keys())
    assert {"run_id", "case_id", "fire_at", "leg_type", "merchant_id"} <= cols
    uniques = {
        tuple(c.name for c in con.columns)
        for con in ScheduledJob.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("run_id",) in uniques  # at most one pending timer per run

    # The poller still claims with FOR UPDATE SKIP LOCKED (D-090 semantics).
    scheduler_src = (REPO_ROOT / "src/torque/execution/scheduler.py").read_text("utf-8")
    assert "with_for_update(skip_locked=True)" in scheduler_src


def test_no_temporal_anywhere() -> None:
    assert importlib.util.find_spec("temporalio") is None
    for rel in ("pyproject.toml", "docker-compose.yml", "Dockerfile"):
        assert "temporal" not in (REPO_ROOT / rel).read_text("utf-8").lower(), rel
