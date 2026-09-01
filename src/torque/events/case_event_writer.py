"""The atomic-write primitive (Blueprint Section 2.3).

> every `Action` write and its corresponding `CaseEvent` write happen inside
> ONE Postgres transaction (`BEGIN...COMMIT`), same database instance.

Milestone 1 delivers the two halves that compose that guarantee:

* `atomic(session)` — a single-transaction scope (`session.begin()`), commits on
  success, rolls back on any exception. Both writes live or die together.
* `append_case_event(...)` — validates the payload against its locked schema and
  stages the `CaseEvent` row on the session.

`write_action_and_event(...)` (the named Module 5 helper) is
`atomic()` + `session.add(action)` + `append_case_event(...)`. It cannot be
finished here because the `Action` model lands in Milestone 3; a stub is
provided so the call site and its contract are already visible.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from torque.enums import Actor, CaseEventType
from torque.events.payloads import validate_payload
from torque.models.case_event import CaseEvent


@contextmanager
def atomic(session: Session) -> Iterator[Session]:
    """Run a block inside one transaction. Commit on success, roll back on error.

    Use for any `Action` + `CaseEvent` pair, and anywhere else two writes must
    be all-or-nothing.
    """
    if session.in_transaction():
        # Nest inside the caller's transaction via a SAVEPOINT so a failure here
        # doesn't silently poison their outer unit of work.
        with session.begin_nested():
            yield session
        return
    with session.begin():
        yield session


def append_case_event(
    session: Session,
    *,
    case_id: uuid.UUID,
    event_type: CaseEventType,
    payload: dict,
    actor: Actor,
    reasoning: str | None = None,
    counterparty_id: uuid.UUID | None = None,
) -> CaseEvent:
    """Validate `payload` against the locked schema for `event_type` and stage a
    `CaseEvent`. Does NOT commit — the caller controls the transaction (usually
    via `atomic`)."""
    validated = validate_payload(event_type, payload)
    row = CaseEvent(
        case_id=case_id,
        counterparty_id=counterparty_id,
        event_type=CaseEventType(event_type),
        payload=validated,
        actor=Actor(actor),
        reasoning=reasoning,
    )
    session.add(row)
    return row


def write_action_and_event(*args, **kwargs):  # pragma: no cover - Milestone 3
    raise NotImplementedError(
        "write_action_and_event lands with the Action model in Milestone 3. "
        "Its contract: `with atomic(session): session.add(action); "
        "append_case_event(session, ...)` — Action and CaseEvent in one "
        "transaction, no exceptions (Blueprint Section 2.3)."
    )
