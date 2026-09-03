"""Module 4 — the activate Celery task (eager path + redelivery idempotency)."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select

from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import CaseStatus, LegType
from torque.models import PlaybookRun
from torque.policy import seed_catalog
from torque.policy.tasks import activate_case_task


def _case(make_case):
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value, diagnosis_confidence=0.9,
        context={"gateway": "razorpay"},
    )


def test_task_creates_run(db, make_case, celery_eager, monkeypatch):
    @contextmanager
    def _fake_scope():
        yield db

    monkeypatch.setattr("torque.policy.tasks._session_scope", _fake_scope)
    seed_catalog(db)
    case = _case(make_case)

    result = activate_case_task.apply(args=(str(case.case_id),)).get()
    assert result == "RUN_CREATED"
    assert db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).one()


def test_task_is_idempotent(db, make_case, celery_eager, monkeypatch):
    @contextmanager
    def _fake_scope():
        yield db

    monkeypatch.setattr("torque.policy.tasks._session_scope", _fake_scope)
    seed_catalog(db)
    case = _case(make_case)

    assert activate_case_task.apply(args=(str(case.case_id),)).get() == "RUN_CREATED"
    assert activate_case_task.apply(args=(str(case.case_id),)).get() == "NOOP"
