"""Module 3 — the diagnose Celery task (eager path + redelivery idempotency)."""

from __future__ import annotations

from contextlib import contextmanager

from torque.diagnosis.tasks import diagnose_case_task
from torque.enums import CaseStatus, LegType


def _payment_case(make_case, decline_code="insufficient_funds"):
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": decline_code},
    )


def test_task_diagnoses_a_case(db, make_case, celery_eager, monkeypatch):
    @contextmanager
    def _fake_scope():
        yield db

    monkeypatch.setattr("torque.diagnosis.tasks._session_scope", _fake_scope)
    case = _payment_case(make_case)

    result = diagnose_case_task.apply(args=(str(case.case_id),)).get()
    assert result == "ROUTED_TO_PLAYBOOK"
    db.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE


def test_task_is_idempotent_under_redelivery(db, make_case, celery_eager, monkeypatch):
    @contextmanager
    def _fake_scope():
        yield db

    monkeypatch.setattr("torque.diagnosis.tasks._session_scope", _fake_scope)
    case = _payment_case(make_case, decline_code="BAD_REQUEST_ERROR")

    first = diagnose_case_task.apply(args=(str(case.case_id),)).get()
    second = diagnose_case_task.apply(args=(str(case.case_id),)).get()
    assert first == "ESCALATED"
    assert second == "NOOP"  # redelivery is a no-op
