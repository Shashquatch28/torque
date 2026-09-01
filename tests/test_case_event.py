"""Blueprint Section 2.3 / Section 4 — CaseEvent is the single, append-only
history mechanism with a locked payload schema per event_type."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from torque.enums import Actor, CaseEventType, LegType
from torque.events import append_case_event, validate_payload
from torque.exceptions import (
    AppendOnlyViolation,
    PayloadValidationError,
    UnknownEventTypeError,
)
from torque.models import RevenueLeakCase


@pytest.fixture()
def case(db, make_merchant, make_counterparty, make_event):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    c = RevenueLeakCase(
        merchant_id=m.merchant_id,
        leg_type=LegType.PAYMENT_DEGRADATION,
        source_event_id=ev.event_id,
        counterparty_id=cp.counterparty_id,
        amount_at_risk=1000,
        context={"gateway": "razorpay"},
    )
    db.add(c)
    db.flush()
    return c


def test_every_event_type_has_a_payload_schema():
    from torque.events.payloads import PAYLOAD_MODELS

    assert set(PAYLOAD_MODELS) == set(CaseEventType)


def test_valid_payload_normalised():
    out = validate_payload(
        CaseEventType.ACTION_BLOCKED,
        {
            "action_id": "11111111-1111-1111-1111-111111111111",
            "action_type": "SEND_WHATSAPP",
            "block_reason": "QUIET_HOURS",
        },
    )
    assert out == {
        "action_id": "11111111-1111-1111-1111-111111111111",
        "action_type": "SEND_WHATSAPP",
        "block_reason": "QUIET_HOURS",
    }


def test_unknown_event_type_rejected():
    with pytest.raises(UnknownEventTypeError):
        validate_payload("NOT_A_REAL_EVENT", {})  # type: ignore[arg-type]


def test_malformed_payload_rejected():
    with pytest.raises(PayloadValidationError):
        validate_payload(CaseEventType.STATUS_CHANGED, {"from_status": "DETECTED"})


def test_append_case_event_persists_with_global_ordering(db, case):
    e1 = append_case_event(
        db,
        case_id=case.case_id,
        event_type=CaseEventType.STATUS_CHANGED,
        payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "t"},
        actor=Actor.SYSTEM,
    )
    e2 = append_case_event(
        db,
        case_id=case.case_id,
        event_type=CaseEventType.DIAGNOSIS_COMPLETED,
        payload={"root_cause_code": "GATEWAY_TIMEOUT", "diagnosis_confidence": 0.5},
        actor=Actor.AGENT,
    )
    db.flush()
    assert e1.event_seq_id < e2.event_seq_id


def test_orm_update_of_case_event_rejected_by_guard(db, case):
    ce = append_case_event(
        db,
        case_id=case.case_id,
        event_type=CaseEventType.HUMAN_RESOLVED,
        payload={"resolution": "x", "agent_id": "a"},
        actor=Actor.HUMAN,
    )
    db.flush()
    ce.reasoning = "tampered"
    with pytest.raises(AppendOnlyViolation):
        db.flush()


def test_orm_delete_of_case_event_rejected_by_guard(db, case):
    ce = append_case_event(
        db,
        case_id=case.case_id,
        event_type=CaseEventType.HUMAN_RESOLVED,
        payload={"resolution": "x", "agent_id": "a"},
        actor=Actor.HUMAN,
    )
    db.flush()
    db.delete(ce)
    with pytest.raises(AppendOnlyViolation):
        db.flush()


def test_raw_sql_update_blocked_by_db_trigger(db, case):
    append_case_event(
        db,
        case_id=case.case_id,
        event_type=CaseEventType.HUMAN_RESOLVED,
        payload={"resolution": "x", "agent_id": "a"},
        actor=Actor.HUMAN,
    )
    db.flush()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE case_event SET reasoning = 'x'"))


def test_raw_sql_delete_blocked_by_db_trigger(db, case):
    append_case_event(
        db,
        case_id=case.case_id,
        event_type=CaseEventType.HUMAN_RESOLVED,
        payload={"resolution": "x", "agent_id": "a"},
        actor=Actor.HUMAN,
    )
    db.flush()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM case_event"))
