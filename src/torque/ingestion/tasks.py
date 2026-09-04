"""Celery tasks for Module 2 inbound work — one per ingestion path across the
four legs, plus the systemic-detection beat job.

Thin on purpose: each opens one transactional `session_scope()`, delegates to
the leg module, and returns a short string for logs / eager assertions. All
logic and idempotency live in the delegated modules.

`_session_scope` is a module-level indirection so tests can bind a task to the
harness session; production always uses `torque.db.session.session_scope`.

**Module 12a — closing the autonomous loop (D-137).** Each case-creating task
below passes `on_case_ready` to its leg module, which *records* the ready
case's id (a plain Python append — no I/O) while the transaction is still
open. Only **after** `with _session_scope()` exits — i.e. only once that
transaction has actually committed — does the task call `dispatch_diagnosis`,
which enqueues `torque.diagnosis.diagnose_case_task`. `dispatch_diagnosis` is
its own module-level name so tests can monkeypatch it exactly like
`_session_scope`.

**`dispatch_diagnosis`'s small `countdown` (D-138).** A real deployment has a
*second*, independent caller of this same function: `torque.demo.scenarios`
(when `dispatch=True`) calls it from *inside* the still-open request
transaction (`torque.api.demo.post_inject`, whose `get_db` dependency commits
only after the handler returns — the same shape `api/webhooks.py` already uses
for its own dispatches). Confirmed against a real worker + a real Postgres
connection (Module 12a's Docker smoke test): with **no** delay, the worker can
receive and run `diagnose_case_task` *before* that commit lands, see no case
(`NOOP`) at all, and never retry. `dispatch_diagnosis` therefore always enqueues
with a short `countdown` — cheap insurance for the (already-safe)
commit-then-dispatch callers above, and the actual fix for the
not-yet-committed one. `task_always_eager` (the test harness only) ignores
`countdown` entirely and still runs inline immediately, so this changes no
test's timing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from torque.db.session import session_scope
from torque.ingestion.celery_app import celery_app

_session_scope = session_scope

#: Cheap insurance against dispatching before the originating write has
#: actually committed (D-138) — comfortably longer than a Postgres commit's
#: round-trip, negligible next to the buffers' 30s/90s windows.
_DIAGNOSIS_DISPATCH_COUNTDOWN_SECONDS = 2


def dispatch_diagnosis(case_id: str) -> None:
    """Enqueue diagnosis for a case whose creation is durable, or about to be
    (Module 12a / D-137 / D-138)."""
    from torque.diagnosis.tasks import diagnose_case_task

    diagnose_case_task.apply_async(
        (case_id,), countdown=_DIAGNOSIS_DISPATCH_COUNTDOWN_SECONDS
    )


@celery_app.task(name="torque.ingestion.resolve_buffered_event", ignore_result=True)
def resolve_buffered_event_task(event_id: str) -> str:
    from torque.ingestion.buffer import resolve_buffered_event

    ready: list[str] = []
    with _session_scope() as session:
        outcome = resolve_buffered_event(
            session,
            event_id=uuid.UUID(str(event_id)),
            on_case_ready=lambda case: ready.append(str(case.case_id)),
        )
    for case_id in ready:
        dispatch_diagnosis(case_id)
    return outcome.name


@celery_app.task(
    name="torque.ingestion.resolve_subscription_buffered_event", ignore_result=True
)
def resolve_subscription_buffered_event_task(event_id: str) -> str:
    """Leg 3 — the 30 s `subscription.charged.failed` self-recovery buffer."""
    from torque.ingestion.subscription import resolve_subscription_buffered_event

    ready: list[str] = []
    with _session_scope() as session:
        outcome = resolve_subscription_buffered_event(
            session,
            event_id=uuid.UUID(str(event_id)),
            on_case_ready=lambda case: ready.append(str(case.case_id)),
        )
    for case_id in ready:
        dispatch_diagnosis(case_id)
    return outcome.name


@celery_app.task(name="torque.ingestion.create_checkout_case", ignore_result=True)
def create_checkout_case_task(event_id: str) -> str:
    """Leg 2 — `checkout.abandoned` (no buffer; runs immediately)."""
    from torque.ingestion.checkout import create_checkout_case

    ready: list[str] = []
    with _session_scope() as session:
        outcome = create_checkout_case(
            session,
            event_id=uuid.UUID(str(event_id)),
            on_case_ready=lambda case: ready.append(str(case.case_id)),
        )
    for case_id in ready:
        dispatch_diagnosis(case_id)
    return outcome.name


@celery_app.task(name="torque.ingestion.ingest_invoice", ignore_result=True)
def ingest_invoice_task(event_id: str) -> str:
    """Leg 4 — `invoice.overdue` → `B2BInvoice` + case grouping (no buffer)."""
    from torque.ingestion.b2b import ingest_invoice

    ready: list[str] = []
    with _session_scope() as session:
        outcome = ingest_invoice(
            session,
            event_id=uuid.UUID(str(event_id)),
            on_case_ready=lambda case: ready.append(str(case.case_id)),
        )
    for case_id in ready:
        dispatch_diagnosis(case_id)
    return outcome.name


@celery_app.task(name="torque.ingestion.detect_systemic", ignore_result=True)
def detect_systemic_task() -> str:
    """The §2.5 60-second job (Milestone 7c). Short-lived, one transaction."""
    from torque.ingestion.systemic import run_systemic_detection

    with _session_scope() as session:
        run_systemic_detection(session, now=datetime.now(UTC))
    return "ok"
