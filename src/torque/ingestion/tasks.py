"""Celery tasks for Module 2 inbound work — one per ingestion path across the
four legs, plus the systemic-detection beat job.

Thin on purpose: each opens one transactional `session_scope()`, delegates to
the leg module, and returns a short string for logs / eager assertions. All
logic and idempotency live in the delegated modules.

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


@celery_app.task(
    name="torque.ingestion.resolve_subscription_buffered_event", ignore_result=True
)
def resolve_subscription_buffered_event_task(event_id: str) -> str:
    """Leg 3 — the 30 s `subscription.charged.failed` self-recovery buffer."""
    from torque.ingestion.subscription import resolve_subscription_buffered_event

    with _session_scope() as session:
        outcome = resolve_subscription_buffered_event(
            session, event_id=uuid.UUID(str(event_id))
        )
    return outcome.name


@celery_app.task(name="torque.ingestion.create_checkout_case", ignore_result=True)
def create_checkout_case_task(event_id: str) -> str:
    """Leg 2 — `checkout.abandoned` (no buffer; runs immediately)."""
    from torque.ingestion.checkout import create_checkout_case

    with _session_scope() as session:
        outcome = create_checkout_case(session, event_id=uuid.UUID(str(event_id)))
    return outcome.name


@celery_app.task(name="torque.ingestion.ingest_invoice", ignore_result=True)
def ingest_invoice_task(event_id: str) -> str:
    """Leg 4 — `invoice.overdue` → `B2BInvoice` + case grouping (no buffer)."""
    from torque.ingestion.b2b import ingest_invoice

    with _session_scope() as session:
        outcome = ingest_invoice(session, event_id=uuid.UUID(str(event_id)))
    return outcome.name


@celery_app.task(name="torque.ingestion.detect_systemic", ignore_result=True)
def detect_systemic_task() -> str:
    """The §2.5 60-second job (Milestone 7c). Short-lived, one transaction."""
    from torque.ingestion.systemic import run_systemic_detection

    with _session_scope() as session:
        run_systemic_detection(session, now=datetime.now(UTC))
    return "ok"
