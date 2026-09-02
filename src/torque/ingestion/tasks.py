"""Celery tasks for Module 2 inbound work.

Thin on purpose: each opens one transactional `session_scope()`, delegates to
`buffer` / `systemic`, and returns a short string for logs / eager assertions.
All logic and idempotency live in the delegated modules.

`_session_scope` is a module-level indirection so tests can bind a task to the
harness session; production always uses `torque.db.session.session_scope`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from torque.db.session import session_scope
from torque.ingestion.celery_app import celery_app

_session_scope = session_scope


@celery_app.task(name="torque.ingestion.resolve_buffered_event", ignore_result=True)
def resolve_buffered_event_task(event_id: str) -> str:
    from torque.ingestion.buffer import resolve_buffered_event

    with _session_scope() as session:
        outcome = resolve_buffered_event(session, event_id=uuid.UUID(str(event_id)))
    return outcome.name


@celery_app.task(name="torque.ingestion.detect_systemic", ignore_result=True)
def detect_systemic_task() -> str:
    """The §2.5 60-second job (Milestone 7c). Short-lived, one transaction."""
    from torque.ingestion.systemic import run_systemic_detection

    with _session_scope() as session:
        run_systemic_detection(session, now=datetime.now(UTC))
    return "ok"
