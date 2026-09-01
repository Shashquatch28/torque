"""The atomic-write primitive (Blueprint Section 2.3).

> every `Action` write and its corresponding `CaseEvent` write happen inside
> ONE Postgres transaction (`BEGIN...COMMIT`), same database instance.

* `atomic(session)` — a single-transaction scope, commits on success, rolls back
  on any exception. Both writes live or die together.
* `append_case_event(...)` — validates the payload against its locked schema and
  stages the `CaseEvent` row.
* `write_action_and_event(...)` — the single sanctioned path for writing an
  `Action`. It persists, in ONE transaction:
    - the `Action`;
    - its `ActionCase` attribution row(s) — every Action has >= 1 (Milestone 5
      deviation 2); a single-case Action gets exactly one row
      (`is_primary`, `credit_weight = Decimal("1.00000")`);
    - one `CaseEvent` (`ACTION_EXECUTED`, or `ACTION_BLOCKED` when
      `outcome == BLOCKED_BY_GUARDRAIL`) carrying `action_id` in its payload as
      the explicit Action<->CaseEvent correlation value.
  The `before_flush` guard (`torque.models.guards`) re-checks all of the above,
  so a bare `session.add(action)` cannot bypass it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from torque.enums import ActionOutcome, Actor, CaseEventType
from torque.events.payloads import validate_payload
from torque.models.case_event import CaseEvent

_FULL_WEIGHT = Decimal("1.00000")


@dataclass(frozen=True)
class Attribution:
    """One `ActionCase` attribution spec for a multi-case `Action`."""

    case_id: uuid.UUID
    is_primary: bool
    credit_weight: Decimal


@contextmanager
def atomic(session: Session) -> Iterator[Session]:
    """Run a block inside one transaction. Commit on success, roll back on error."""
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


def _build_action_cases(action, attributions: Sequence[Attribution] | None):
    from torque.models.action_case import ActionCase

    if attributions is None:
        return [
            ActionCase(
                action_id=action.action_id,
                case_id=action.primary_case_id,
                merchant_id=action.merchant_id,
                is_primary=True,
                credit_weight=_FULL_WEIGHT,
            )
        ]
    return [
        ActionCase(
            action_id=action.action_id,
            case_id=a.case_id,
            merchant_id=action.merchant_id,
            is_primary=a.is_primary,
            credit_weight=Decimal(str(a.credit_weight)),
        )
        for a in attributions
    ]


def _event_for(action) -> tuple[CaseEventType, dict]:
    action_id = str(action.action_id)
    if ActionOutcome(action.outcome) is ActionOutcome.BLOCKED_BY_GUARDRAIL:
        return CaseEventType.ACTION_BLOCKED, {
            "action_id": action_id,
            "action_type": action.action_type,
            "block_reason": action.block_reason,
        }
    return CaseEventType.ACTION_EXECUTED, {
        "action_id": action_id,
        "action_type": action.action_type,
        "channel": action.channel,
        "outcome": action.outcome,
        "cost": action.cost,
    }


def write_action_and_event(
    session: Session,
    *,
    action,
    actor: Actor,
    reasoning: str | None = None,
    attributions: Sequence[Attribution] | None = None,
    counterparty_id: uuid.UUID | None = None,
):
    """Persist `action`, its `ActionCase` attribution row(s), and the correlated
    `CaseEvent` in one transaction (Blueprint Section 2.3).

    `attributions=None`  -> single-case: one `ActionCase` for
                            `action.primary_case_id`.
    `attributions=[...]` -> multi-case: one `ActionCase` per `Attribution`;
                            exactly one `is_primary` (its `case_id` must equal
                            `action.primary_case_id`); Σ `credit_weight` must be
                            exactly Decimal("1.00000").
    """
    # The `action_id` column default is flush-time; assign it now so the
    # ActionCase rows and the correlation payload can reference it.
    if action.action_id is None:
        action.action_id = uuid.uuid4()

    event_type, payload = _event_for(action)
    with atomic(session):
        session.add(action)
        for row in _build_action_cases(action, attributions):
            session.add(row)
        append_case_event(
            session,
            case_id=action.primary_case_id,
            event_type=event_type,
            payload=payload,
            actor=actor,
            reasoning=reasoning,
            counterparty_id=counterparty_id,
        )
    return action
