"""Celery tasks for Module 8 — Recovery Scoring recompute (§8.5).

Two entry points, both thin (open one transactional `session_scope()`, delegate,
return a short string) — the same posture as `torque.diagnosis.tasks` /
`torque.reconciliation.tasks`. **No new scheduling architecture** (D-112): these
run on the existing Celery + Redis app, and the daily sweep is one extra
`beat_schedule` entry in `torque.ingestion.celery_app`.

* `recompute_recovery_score_task(case_id)` — re-score one case. Idempotent;
  a terminal case is a no-op.
* `recompute_open_case_scores_task()` — the §8.5 item-3 daily sweep: re-score
  every open case (all merchants) and refresh queued cases' `priority`.

The §8.5 item-1 (case creation) and item-2 (diagnosis completion) recomputes are
wired **inline** in the ingestion / diagnosis transactions (they only set derived
columns — no `CaseEvent`, no status change), so they need no task.
"""

from __future__ import annotations

import uuid

from torque.db.session import session_scope
from torque.ingestion.celery_app import celery_app
from torque.scoring.score import recompute_open_cases, score_case

_session_scope = session_scope


@celery_app.task(name="torque.scoring.recompute_recovery_score", ignore_result=True)
def recompute_recovery_score_task(case_id: str) -> str:
    """Re-score one case by id (Blueprint §8.5). Idempotent; terminal → no-op."""
    from torque.models import RevenueLeakCase

    with _session_scope() as session:
        case = session.get(RevenueLeakCase, uuid.UUID(str(case_id)))
        if case is None:
            return "MISSING"
        result = score_case(session, case)
    return "SCORED" if result is not None else "SKIPPED_TERMINAL"


@celery_app.task(name="torque.scoring.recompute_open_case_scores", ignore_result=True)
def recompute_open_case_scores_task() -> str:
    """The §8.5 daily sweep — re-score every open case across all merchants."""
    with _session_scope() as session:
        count = recompute_open_cases(session)
    return f"SCORED {count}"
