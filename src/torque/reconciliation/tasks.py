"""Celery task for Module 7 — one reconciliation per verified success `Event`.

Thin: opens one transactional `session_scope()`, delegates to
`reconcile.reconcile_event`, returns a short string for logs / eager assertions.
All logic and idempotency live in the engine. `_session_scope` is a module-level
indirection so tests can bind the task to the harness session.
"""

from __future__ import annotations

import uuid

from torque.db.session import session_scope
from torque.ingestion.celery_app import celery_app

_session_scope = session_scope


@celery_app.task(name="torque.reconciliation.reconcile_event", ignore_result=True)
def reconcile_event_task(event_id: str) -> str:
    from torque.reconciliation.reconcile import reconcile_event

    with _session_scope() as session:
        outcome = reconcile_event(session, event_id=uuid.UUID(str(event_id)))
    return outcome.name
