"""Shared builders for the Module 9 reporting tests.

Not a `test_` module — pytest does not collect it. These set the recovery
fields Module 7 owns (`recovery_type` / `recovered_amount`, guarded — written
inside `guards.module7_writer`) and drive case status directly (status has no
`before_flush` guard). Actions go through the real `write_action_and_event`
path so `ActionCase` attribution is coherent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from torque.enums import (
    ActionOutcome,
    ActionType,
    Actor,
    BlockReason,
    CaseStatus,
    RecoveryType,
)
from torque.events import Attribution, write_action_and_event
from torque.models import Action, B2BInvoice
from torque.models.guards import module7_writer

DEFAULT_CLOSED_AT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def set_recovery(
    db,
    case,
    *,
    recovery_type: RecoveryType,
    amount,
    status: CaseStatus = CaseStatus.RECOVERED,
    closed_at: datetime | None = DEFAULT_CLOSED_AT,
):
    """Mark `case` recovered the way Module 7 reconciliation would."""
    case.status = status
    with module7_writer(db):
        case.recovery_type = recovery_type
        case.recovered_amount = Decimal(str(amount))
        case.closed_at = closed_at
        db.flush()
    return case


def set_status(db, case, status: CaseStatus, *, closed_at: datetime | None = None):
    case.status = status
    if closed_at is not None:
        case.closed_at = closed_at
    db.flush()
    return case


def add_action(
    db,
    case,
    *,
    action_type: ActionType = ActionType.SEND_WHATSAPP,
    outcome: ActionOutcome = ActionOutcome.SUCCESS,
    channel: str | None = "whatsapp",
    block_reason: BlockReason | None = None,
    cost=None,
    executed_at: datetime | None = DEFAULT_CLOSED_AT,
) -> Action:
    blocked = outcome is ActionOutcome.BLOCKED_BY_GUARDRAIL
    action = Action(
        merchant_id=case.merchant_id,
        primary_case_id=case.case_id,
        run_id=None,
        action_type=action_type,
        channel=channel,
        executed_at=None if blocked else executed_at,
        outcome=outcome,
        block_reason=(block_reason or BlockReason.QUIET_HOURS) if blocked else None,
        cost=Decimal(str(cost)) if cost is not None else None,
    )
    write_action_and_event(
        db,
        action=action,
        actor=Actor.SYSTEM,
        attributions=[
            Attribution(case_id=case.case_id, is_primary=True, credit_weight=Decimal("1.00000"))
        ],
    )
    return action


def add_invoice(db, case, *, original, outstanding=None, due_date=None):
    from datetime import date

    inv = B2BInvoice(
        merchant_id=case.merchant_id,
        case_id=case.case_id,
        counterparty_id=case.counterparty_id,
        due_date=due_date or date(2026, 8, 1),
        days_overdue=30,
        original_amount=Decimal(str(original)),
        outstanding_amount=Decimal(str(original if outstanding is None else outstanding)),
    )
    db.add(inv)
    db.flush()
    return inv
