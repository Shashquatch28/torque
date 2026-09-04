"""Module 3 — the diagnose Celery task (eager path + redelivery idempotency).

Module 12a: `diagnose_case_task` now dispatches `torque.policy.activate_case_task`
on `ROUTED_TO_PLAYBOOK` (D-137) — `test_task_diagnoses_a_case` binds *both*
tasks' `_session_scope` to the harness session and seeds the catalog so the
chain actually runs (and is asserted on), rather than silently no-op-ing against
an invisible, uncommitted case in a second real connection.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select

from torque.diagnosis.tasks import diagnose_case_task
from torque.enums import CaseStatus, LegType
from torque.models import PlaybookRun, ScheduledJob
from torque.policy.catalog import seed_catalog


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
    monkeypatch.setattr("torque.policy.tasks._session_scope", _fake_scope)
    seed_catalog(db)
    case = _payment_case(make_case)

    result = diagnose_case_task.apply(args=(str(case.case_id),)).get()
    assert result == "ROUTED_TO_PLAYBOOK"
    db.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE

    # Module 12a: diagnosis routing to a playbook automatically activated it —
    # a run was created and its first timer armed — with no manual call to
    # either engine.
    run = db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).one()
    assert db.scalars(
        select(ScheduledJob).where(ScheduledJob.run_id == run.run_id)
    ).one()


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
