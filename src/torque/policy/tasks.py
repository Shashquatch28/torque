"""Celery task for Module 4 — Policy & Playbook Engine.

Selecting a playbook and instantiating a run is short-lived, stateless work — the
same class as Module 2 ingestion and Module 3 diagnosis, and explicitly NOT the
durable execution workflow (that is Module 5's Temporal territory, U-07). Thin:
open one `session_scope()`, delegate to `activate_case`, return a short string.

As with Module 3 (D-080), wiring the automatic *enqueue* of this task from Module
3's diagnosis completion is deliberately NOT done here — an inline eager enqueue
would run activation synchronously inside diagnosis and change Module 3's tested
post-diagnosis contract (cases end `PLAYBOOK_ACTIVE`, no run yet). The engine +
task are the finished, independently-invocable Module 4 surface; the cross-module
trigger is an orchestration-layer concern (D-088).
"""

from __future__ import annotations

import uuid

from torque.db.session import session_scope
from torque.ingestion.celery_app import celery_app
from torque.policy.engine import activate_case

_session_scope = session_scope


@celery_app.task(name="torque.policy.activate_case", ignore_result=True)
def activate_case_task(case_id: str) -> str:
    """Activate one diagnosed case (Blueprint §4). Idempotent under redelivery."""
    with _session_scope() as session:
        outcome = activate_case(session, case_id=uuid.UUID(str(case_id)))
    return outcome.name
