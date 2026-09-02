"""The §2.3 same-session self-recovery buffer (Milestone 7b, Leg 1).

`resolve_buffered_event` is what the Celery delayed task runs when the 90 s
buffer elapses for a `payment.failed` `Event`:

* Event gone / already `processed` / not `payment.failed`  → `NOOP` (idempotent
  under Celery redelivery).
* A `payment.captured` for the same `payment_id`/`order_id`, received at or
  after the failure  → `Event.processed = True`, no case, `SELF_RECOVERED`.
* Otherwise  → hand off to `cases.create_or_attach_case` (which runs the §2.4
  dedup check and creates the `PAYMENT_DEGRADATION` case).

The Celery task wraps this in one `session_scope()` transaction — a failure at
any point rolls the whole thing back (no partial case / merge / budget /
`processed` flag).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.config import get_policy
from torque.ingestion import payloads
from torque.ingestion.cases import create_or_attach_case
from torque.ingestion.outcomes import BufferOutcome
from torque.models import Event

PAYMENT_FAILED = "payment.failed"
PAYMENT_CAPTURED = "payment.captured"


def payment_failure_buffer_seconds() -> int:
    """The §2.3 buffer delay for `payment.failed` (default 90 s, tunable via
    `PolicyConfig.payment_failure_buffer_seconds`)."""
    return get_policy().payment_failure_buffer_seconds


def resolve_buffered_event(session: Session, *, event_id) -> BufferOutcome:
    event = session.get(Event, event_id)
    if event is None or event.processed or event.type != PAYMENT_FAILED:
        return BufferOutcome.NOOP

    if _has_interim_capture(session, event):
        event.processed = True
        session.flush()
        return BufferOutcome.SELF_RECOVERED

    return create_or_attach_case(session, event=event)


def _has_interim_capture(session: Session, failure_event: Event) -> bool:
    payload = failure_event.raw_payload or {}
    pid = payloads.payment_id(payload)
    oid = payloads.order_id(payload)
    if not pid and not oid:
        return False

    captures = session.scalars(
        select(Event)
        .where(Event.merchant_id == failure_event.merchant_id)
        .where(Event.type == PAYMENT_CAPTURED)
        .where(Event.received_at >= failure_event.received_at)
    )
    for capture in captures:
        cap_payload = capture.raw_payload or {}
        if pid and payloads.payment_id(cap_payload) == pid:
            return True
        if oid and payloads.order_id(cap_payload) == oid:
            return True
    return False
