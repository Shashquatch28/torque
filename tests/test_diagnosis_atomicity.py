"""Module 3 — transactional atomicity (Blueprint §2.3 discipline).

A diagnosis mutates several pieces of domain state (status transition(s) + case
fields + CaseEvent). If any write fails, the whole diagnosis must roll back — no
half-diagnosed case (a DIAGNOSING status with no completion event, say).
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from torque.diagnosis import diagnose_case
from torque.enums import CaseEventType, CaseStatus, LegType
from torque.models import CaseEvent


def _payment_case(make_case):
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "insufficient_funds"},
    )


def _events(db, case, event_type=None):
    stmt = select(func.count()).select_from(CaseEvent).where(CaseEvent.case_id == case.case_id)
    if event_type is not None:
        stmt = stmt.where(CaseEvent.event_type == event_type)
    return int(db.scalar(stmt))


def test_failure_midway_rolls_back_everything(db, make_case, monkeypatch):
    case = _payment_case(make_case)

    # Fail while writing the DIAGNOSIS_COMPLETED event — after the case has
    # already been moved to DIAGNOSING in memory.
    def _boom(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr("torque.diagnosis.engine.append_case_event", _boom)

    with pytest.raises(RuntimeError, match="injected failure"):
        diagnose_case(db, case_id=case.case_id)

    db.refresh(case)
    assert case.status is CaseStatus.DETECTED  # transition rolled back
    assert case.root_cause_code is None
    assert case.diagnosis_confidence is None
    assert _events(db, case) == 0  # no STATUS_CHANGED, no DIAGNOSIS_COMPLETED


def test_success_persists_all_three_pieces(db, make_case):
    case = _payment_case(make_case)
    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)

    assert case.status is CaseStatus.PLAYBOOK_ACTIVE
    assert case.root_cause_code is not None
    assert _events(db, case, CaseEventType.DIAGNOSIS_COMPLETED) == 1
    assert _events(db, case, CaseEventType.STATUS_CHANGED) == 2  # →DIAGNOSING, →PLAYBOOK
