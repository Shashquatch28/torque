"""Agent Console human overrides — Blueprint §4 / §10.8.

`resolve_escalation`, `pause_case`, `unpause_case`. Every function:

* is **tenant-scoped** — the case is fetched through `TenantScope`; a case that
  belongs to another merchant is invisible (`CaseNotFoundError` → HTTP 404),
  never a cross-tenant write;
* validates the **current status** against the control (a control that does not
  apply raises `HumanResolutionError`);
* uses the **existing legal `state_machine` edges** — no new transition;
* does **not** commit — the caller (the FastAPI `get_db` dependency) owns the
  transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.orm import Session

from torque.coordination import human_queue
from torque.db.scoped import TenantScope
from torque.enums import Actor, CaseEventType, CaseStatus, LegType, RecoveryType
from torque.events.case_event_writer import append_case_event
from torque.exceptions import CaseNotFoundError, HumanResolutionError
from torque.models import RevenueLeakCase
from torque.models.guards import human_resolution_writer
from torque.state_machine import transition_case

_ZERO = Decimal("0")


class EscalationResolution(StrEnum):
    """How a human closed a case out of `ESCALATED_TO_HUMAN`. Stored as a plain
    string on `RevenueLeakCase.escalation_resolution` (vocabulary owned here, not
    a Postgres enum — same posture as `HumanQueueReason`)."""

    RECOVERED_BY_HUMAN = "RECOVERED_BY_HUMAN"
    PARTIALLY_RECOVERED_BY_HUMAN = "PARTIALLY_RECOVERED_BY_HUMAN"
    WRITTEN_OFF = "WRITTEN_OFF"


_RESOLUTION_TARGET: dict[EscalationResolution, CaseStatus] = {
    EscalationResolution.RECOVERED_BY_HUMAN: CaseStatus.RECOVERED,
    EscalationResolution.PARTIALLY_RECOVERED_BY_HUMAN: CaseStatus.PARTIALLY_RECOVERED,
    EscalationResolution.WRITTEN_OFF: CaseStatus.WRITTEN_OFF,
}
_RECOVERING = frozenset(
    {
        EscalationResolution.RECOVERED_BY_HUMAN,
        EscalationResolution.PARTIALLY_RECOVERED_BY_HUMAN,
    }
)


@dataclass(frozen=True)
class ResolveOutcome:
    case_id: str
    from_status: str
    to_status: str
    resolution: str
    resolved_by: str
    recovered_amount: Decimal | None


def _get_case(session: Session, merchant_id: str, case_id: uuid.UUID) -> RevenueLeakCase:
    case = TenantScope(session, merchant_id).get(RevenueLeakCase, case_id)
    if case is None:
        raise CaseNotFoundError(f"case {case_id} not found for merchant {merchant_id!r}")
    return case


def resolve_escalation(
    session: Session,
    *,
    merchant_id: str,
    case_id: uuid.UUID,
    resolution: EscalationResolution | str,
    agent_id: str,
    recovered_amount: Decimal | str | None = None,
    now: datetime | None = None,
) -> ResolveOutcome:
    """Close an `ESCALATED_TO_HUMAN` case on a human agent's decision (§10.8).

    `RECOVERED_BY_HUMAN` / `PARTIALLY_RECOVERED_BY_HUMAN` require a positive
    `recovered_amount` (defaults to the case's `amount_at_risk` for a full
    recovery); `WRITTEN_OFF` takes none.
    """
    now = now or datetime.now(UTC)
    resolution = EscalationResolution(resolution)
    if not agent_id:
        raise HumanResolutionError("agent_id is required")

    case = _get_case(session, merchant_id, case_id)
    if CaseStatus(case.status) is not CaseStatus.ESCALATED_TO_HUMAN:
        raise HumanResolutionError(
            f"resolve applies only to an ESCALATED_TO_HUMAN case; "
            f"case {case_id} is {case.status}"
        )

    target = _RESOLUTION_TARGET[resolution]
    at_risk = Decimal(str(case.amount_at_risk or 0))
    amount: Decimal | None = None
    if resolution in _RECOVERING:
        amount = (
            at_risk
            if recovered_amount is None
            else Decimal(str(recovered_amount))
        )
        if amount <= _ZERO:
            raise HumanResolutionError(
                "a recovering resolution needs a positive recovered_amount"
            )
        if amount > at_risk and resolution is EscalationResolution.RECOVERED_BY_HUMAN:
            # a full recovery cannot exceed the exposure; a partial can be capped
            amount = at_risk

    from_status = str(case.status)
    is_b2b = LegType(case.leg_type) is LegType.B2B_RECEIVABLE
    partial_b2b_stays_open = (
        resolution is EscalationResolution.PARTIALLY_RECOVERED_BY_HUMAN and is_b2b
    )

    with human_resolution_writer(session):
        transition_case(
            session,
            case,
            target,
            trigger="human_resolved",
            actor=Actor.HUMAN,
            reasoning=f"Agent {agent_id} resolved: {resolution.value}",
        )
        case.escalation_resolution = resolution.value
        case.escalation_resolved_by = agent_id
        case.escalation_resolved_at = now
        if amount is not None:
            case.recovery_type = RecoveryType.AGENT_ASSISTED
            case.recovered_amount = (case.recovered_amount or _ZERO) + amount
        if not partial_b2b_stays_open:
            case.closed_at = now
        append_case_event(
            session,
            case_id=case.case_id,
            event_type=CaseEventType.HUMAN_RESOLVED,
            payload={"resolution": resolution.value, "agent_id": agent_id},
            actor=Actor.HUMAN,
            reasoning=f"Human agent resolved case as {resolution.value}",
            counterparty_id=case.counterparty_id,
        )
        human_queue.remove_for_case(session, case)
        session.flush()

    return ResolveOutcome(
        case_id=str(case.case_id),
        from_status=from_status,
        to_status=str(case.status),
        resolution=resolution.value,
        resolved_by=agent_id,
        recovered_amount=case.recovered_amount,
    )


def pause_case(
    session: Session,
    *,
    merchant_id: str,
    case_id: uuid.UUID,
    agent_id: str,
    now: datetime | None = None,
) -> ResolveOutcome:
    """`PLAYBOOK_ACTIVE → PAUSED` — a human takes a queued (broken-promise /
    open-conversation) case out of automated playbook execution (§4)."""
    return _toggle(
        session,
        merchant_id=merchant_id,
        case_id=case_id,
        agent_id=agent_id,
        require=CaseStatus.PLAYBOOK_ACTIVE,
        target=CaseStatus.PAUSED,
        trigger="human_paused",
        now=now,
    )


def unpause_case(
    session: Session,
    *,
    merchant_id: str,
    case_id: uuid.UUID,
    agent_id: str,
    now: datetime | None = None,
) -> ResolveOutcome:
    """`PAUSED → PLAYBOOK_ACTIVE` — hand the case back to automation (§4)."""
    return _toggle(
        session,
        merchant_id=merchant_id,
        case_id=case_id,
        agent_id=agent_id,
        require=CaseStatus.PAUSED,
        target=CaseStatus.PLAYBOOK_ACTIVE,
        trigger="human_unpaused",
        now=now,
    )


def _toggle(
    session: Session,
    *,
    merchant_id: str,
    case_id: uuid.UUID,
    agent_id: str,
    require: CaseStatus,
    target: CaseStatus,
    trigger: str,
    now: datetime | None,
) -> ResolveOutcome:
    now = now or datetime.now(UTC)
    if not agent_id:
        raise HumanResolutionError("agent_id is required")
    case = _get_case(session, merchant_id, case_id)
    if CaseStatus(case.status) is not require:
        raise HumanResolutionError(
            f"{trigger} applies only to a {require.value} case; "
            f"case {case_id} is {case.status}"
        )
    from_status = str(case.status)
    transition_case(
        session,
        case,
        target,
        trigger=trigger,
        actor=Actor.HUMAN,
        reasoning=f"Agent {agent_id}: {trigger}",
    )
    session.flush()
    return ResolveOutcome(
        case_id=str(case.case_id),
        from_status=from_status,
        to_status=str(case.status),
        resolution=trigger,
        resolved_by=agent_id,
        recovered_amount=None,
    )


__all__ = [
    "EscalationResolution",
    "ResolveOutcome",
    "pause_case",
    "resolve_escalation",
    "unpause_case",
]
