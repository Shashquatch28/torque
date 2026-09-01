"""Blueprint Section 2.3 — the atomic-write primitive. Two writes inside
`atomic(session)` live or die together; a failure rolls back the sibling."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from torque.enums import Actor, CaseEventType, LegType
from torque.events import append_case_event, atomic
from torque.exceptions import PayloadValidationError
from torque.models import CaseEvent, RevenueLeakCase


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


def _event_count(db, case_id) -> int:
    return db.scalar(
        select(func.count()).select_from(CaseEvent).where(CaseEvent.case_id == case_id)
    )


def test_exception_in_block_rolls_back_the_staged_write(db, case):
    before = _event_count(db, case.case_id)
    with pytest.raises(RuntimeError):
        with atomic(db):
            append_case_event(
                db,
                case_id=case.case_id,
                event_type=CaseEventType.STATUS_CHANGED,
                payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "t"},
                actor=Actor.SYSTEM,
            )
            db.flush()
            raise RuntimeError("boom after the insert")
    assert _event_count(db, case.case_id) == before


def test_bad_payload_rolls_back_a_prior_good_write_in_same_block(db, case):
    before = _event_count(db, case.case_id)
    with pytest.raises(PayloadValidationError):
        with atomic(db):
            append_case_event(
                db,
                case_id=case.case_id,
                event_type=CaseEventType.STATUS_CHANGED,
                payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "t"},
                actor=Actor.SYSTEM,
            )
            db.flush()
            append_case_event(
                db,
                case_id=case.case_id,
                event_type=CaseEventType.STATUS_CHANGED,
                payload={"from_status": "DETECTED"},  # malformed
                actor=Actor.SYSTEM,
            )
    assert _event_count(db, case.case_id) == before


def test_success_commits_both(db, case):
    before = _event_count(db, case.case_id)
    with atomic(db):
        append_case_event(
            db,
            case_id=case.case_id,
            event_type=CaseEventType.STATUS_CHANGED,
            payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "t"},
            actor=Actor.SYSTEM,
        )
        append_case_event(
            db,
            case_id=case.case_id,
            event_type=CaseEventType.DIAGNOSIS_COMPLETED,
            payload={"root_cause_code": "GATEWAY_TIMEOUT", "diagnosis_confidence": 0.5},
            actor=Actor.AGENT,
        )
    assert _event_count(db, case.case_id) == before + 2
