"""Locked `CaseEvent.payload` schemas — Blueprint v7 Section 4.

"No `event_type` may be written without a matching schema in this table."
`validate_payload` is the enforcement point; `append_case_event` calls it.

`STEP_TRANSITIONED`'s shape is the blueprint's proposed default and is flagged
PROVISIONAL (Part E item 3).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, ValidationError

from torque.enums import (
    ActionOutcome,
    ActionType,
    Actor,  # noqa: F401  (re-exported for callers building payloads)
    BlockReason,
    CaseEventType,
    CaseStatus,
    MacTier,
    RecoveryType,
    SystemicScope,
)
from torque.exceptions import PayloadValidationError, UnknownEventTypeError


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusChangedPayload(_Payload):
    from_status: CaseStatus
    to_status: CaseStatus
    trigger: str


class DiagnosisCompletedPayload(_Payload):
    root_cause_code: str
    diagnosis_confidence: float
    network_directive: dict | None = None


class ActionExecutedPayload(_Payload):
    # `action_id` is the explicit Action<->CaseEvent correlation value (Milestone
    # 5). CaseEvent gains NO action_id column or FK — the string lives only in
    # the payload and is checked by the before_flush atomicity guard.
    action_id: str
    action_type: ActionType
    # Nullable (Milestone 5 deviation 3): cost computation is deferred and some
    # action types (e.g. RETRY_PAYMENT) have no messaging channel.
    channel: str | None = None
    outcome: ActionOutcome
    cost: Decimal | None = None


class ActionBlockedPayload(_Payload):
    action_id: str
    action_type: ActionType
    block_reason: BlockReason


class NetworkDirectiveReceivedPayload(_Payload):
    mac_code: str
    tier: MacTier
    attempt_number: int
    received_at: datetime


class PromiseCapturedPayload(_Payload):
    promised_amount: Decimal
    promised_date: date


class PaymentReconciledPayload(_Payload):
    recovered_amount: Decimal
    recovery_type: RecoveryType


class SystemicHoldAppliedPayload(_Payload):
    systemic_event_id: str
    issuer_code: str | None = None
    scope: SystemicScope


class HumanResolvedPayload(_Payload):
    resolution: str
    agent_id: str


class StepTransitionedPayload(_Payload):
    # SETTLED by Module 5 (D-091, resolves U-02 / Part E item 3). The execution
    # loop is the first and only writer, so the shape is fixed to what
    # reconstructing a run's traversal actually needs: run attribution, the step
    # just executed, the outcome that drove edge selection, and the next step —
    # nullable because a terminal node has no next step / edge (the run finalized).
    run_id: str
    from_step_id: str
    outcome: str
    to_step_id: str | None = None
    edge_condition: str | None = None


PAYLOAD_MODELS: dict[CaseEventType, type[_Payload]] = {
    CaseEventType.STATUS_CHANGED: StatusChangedPayload,
    CaseEventType.DIAGNOSIS_COMPLETED: DiagnosisCompletedPayload,
    CaseEventType.ACTION_EXECUTED: ActionExecutedPayload,
    CaseEventType.ACTION_BLOCKED: ActionBlockedPayload,
    CaseEventType.NETWORK_DIRECTIVE_RECEIVED: NetworkDirectiveReceivedPayload,
    CaseEventType.PROMISE_CAPTURED: PromiseCapturedPayload,
    CaseEventType.PAYMENT_RECONCILED: PaymentReconciledPayload,
    CaseEventType.SYSTEMIC_HOLD_APPLIED: SystemicHoldAppliedPayload,
    CaseEventType.HUMAN_RESOLVED: HumanResolvedPayload,
    CaseEventType.STEP_TRANSITIONED: StepTransitionedPayload,
}

# Fail loudly at import time if the blueprint's enum and this registry drift.
_missing = set(CaseEventType) - set(PAYLOAD_MODELS)
if _missing:  # pragma: no cover - guards against an incomplete edit
    raise RuntimeError(f"CaseEvent payload schema missing for: {sorted(_missing)}")


def validate_payload(event_type: CaseEventType, raw: dict) -> dict:
    try:
        model = PAYLOAD_MODELS[CaseEventType(event_type)]
    except (KeyError, ValueError) as exc:
        raise UnknownEventTypeError(
            f"no payload schema for event_type {event_type!r}"
        ) from exc
    try:
        parsed = model.model_validate(raw)
    except ValidationError as exc:
        raise PayloadValidationError(
            f"invalid payload for {event_type}: {exc.errors(include_url=False)}"
        ) from exc
    return parsed.model_dump(mode="json")
