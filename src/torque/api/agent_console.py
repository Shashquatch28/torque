"""Module 10 — the Agent Console write surface (Blueprint §4 / §10.8).

Three `POST` endpoints, one per manual override. Domain logic lives in
`torque.agent_console.resolve`; the router only translates HTTP ↔ that call and
maps domain errors to status codes:

* `CaseNotFoundError`     → 404 (unknown / cross-tenant case — never a leak)
* `HumanResolutionError`  → 409 (the control does not apply to the case's state,
  or the inputs are invalid)
* `IllegalTransitionError` → 409 (defensive — the resolve targets are already
  legal `state_machine` edges)

`get_db` commits on a clean return, so a successful override is persisted; any
raised error rolls the transaction back.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from torque.agent_console import (
    EscalationResolution,
    ResolveOutcome,
    pause_case,
    resolve_escalation,
    unpause_case,
)
from torque.api.deps import get_db
from torque.exceptions import (
    CaseNotFoundError,
    HumanResolutionError,
    IllegalTransitionError,
)
from torque.models import Merchant

router = APIRouter(prefix="/agent-console/{merchant_id}", tags=["agent-console"])


class ResolveBody(BaseModel):
    resolution: str = Field(
        description="RECOVERED_BY_HUMAN | PARTIALLY_RECOVERED_BY_HUMAN | WRITTEN_OFF"
    )
    agent_id: str = Field(min_length=1, max_length=64)
    recovered_amount: str | None = Field(
        default=None,
        description="required (as a decimal string) for a recovering resolution; "
        "omit for a full recovery (defaults to amount_at_risk) or a write-off",
    )


class AgentBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)


class ResolveResponse(BaseModel):
    case_id: str
    from_status: str
    to_status: str
    resolution: str
    resolved_by: str
    recovered_amount: Decimal | None


def _response(outcome: ResolveOutcome) -> ResolveResponse:
    return ResolveResponse(
        case_id=outcome.case_id,
        from_status=outcome.from_status,
        to_status=outcome.to_status,
        resolution=outcome.resolution,
        resolved_by=outcome.resolved_by,
        recovered_amount=outcome.recovered_amount,
    )


def _require_merchant(session: Session, merchant_id: str) -> None:
    if session.get(Merchant, merchant_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown merchant {merchant_id!r}")


def _run(fn, /, **kw) -> ResolveResponse:
    try:
        return _response(fn(**kw))
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (HumanResolutionError, IllegalTransitionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/cases/{case_id}/resolve", response_model=ResolveResponse)
def resolve(
    merchant_id: str,
    case_id: uuid.UUID,
    body: ResolveBody,
    session: Session = Depends(get_db),
) -> ResolveResponse:
    """§10.8 — close an `ESCALATED_TO_HUMAN` case on a human agent's decision:
    `→ {RECOVERED, PARTIALLY_RECOVERED, WRITTEN_OFF}` + `escalation_resolution`
    + a `HUMAN_RESOLVED` event + removal from the human queue."""
    _require_merchant(session, merchant_id)
    try:
        resolution = EscalationResolution(body.resolution)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"unknown resolution {body.resolution!r}"
        ) from exc
    amount = None
    if body.recovered_amount is not None:
        try:
            amount = Decimal(body.recovered_amount)
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="recovered_amount is not a valid decimal"
            ) from exc
    return _run(
        resolve_escalation,
        session=session,
        merchant_id=merchant_id,
        case_id=case_id,
        resolution=resolution,
        agent_id=body.agent_id,
        recovered_amount=amount,
    )


@router.post("/cases/{case_id}/pause", response_model=ResolveResponse)
def pause(
    merchant_id: str,
    case_id: uuid.UUID,
    body: AgentBody,
    session: Session = Depends(get_db),
) -> ResolveResponse:
    """§10.8 — `PLAYBOOK_ACTIVE → PAUSED`."""
    _require_merchant(session, merchant_id)
    return _run(
        pause_case,
        session=session,
        merchant_id=merchant_id,
        case_id=case_id,
        agent_id=body.agent_id,
    )


@router.post("/cases/{case_id}/unpause", response_model=ResolveResponse)
def unpause(
    merchant_id: str,
    case_id: uuid.UUID,
    body: AgentBody,
    session: Session = Depends(get_db),
) -> ResolveResponse:
    """§10.8 — `PAUSED → PLAYBOOK_ACTIVE` (hand the case back to automation)."""
    _require_merchant(session, merchant_id)
    return _run(
        unpause_case,
        session=session,
        merchant_id=merchant_id,
        case_id=case_id,
        agent_id=body.agent_id,
    )
