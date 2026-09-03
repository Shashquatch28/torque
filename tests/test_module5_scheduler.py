"""Module 5 — the Postgres-polling scheduler (Blueprint §5.6)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from torque.enums import LegType
from torque.execution import claim_due_jobs, schedule_run
from torque.execution.scheduler import OTHER_LEGS, PAYMENT_LEGS
from torque.models import ScheduledJob


def test_schedule_run_arms_entry_timer(db, make_active_run):
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    assert job is not None
    assert job.run_id == run.run_id
    assert job.case_id == case.case_id
    assert job.leg_type is LegType.PAYMENT_DEGRADATION
    assert job.merchant_id == run.merchant_id


def test_schedule_run_is_idempotent(db, make_active_run):
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    again = schedule_run(db, run_id=run.run_id)
    assert again.job_id == job.job_id  # the same pending timer, not a second one


def test_one_pending_job_per_run_enforced(db, make_active_run):
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    db.add(
        ScheduledJob(
            merchant_id=run.merchant_id, run_id=run.run_id, case_id=case.case_id,
            fire_at=job.fire_at, leg_type=LegType.PAYMENT_DEGRADATION,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_schedule_missing_run_is_none(db):
    assert schedule_run(db, run_id=uuid.uuid4()) is None


def test_poller_stratification(db, make_active_run):
    """A PAYMENT_DEGRADATION job is claimed by the 10 s payment poller, never by the
    60 s other-legs poller (§5.6)."""
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    assert claim_due_jobs(db, leg_types=OTHER_LEGS, now=job.fire_at) == []
    claimed = claim_due_jobs(db, leg_types=PAYMENT_LEGS, now=job.fire_at)
    assert [j.run_id for j in claimed] == [run.run_id]


def test_b2b_job_in_other_stratum(db, make_active_run):
    case, run, job = make_active_run(
        leg=LegType.B2B_RECEIVABLE, root_cause_code="LIQUIDITY_DELAY_LOW_RISK", context={}
    )
    assert claim_due_jobs(db, leg_types=PAYMENT_LEGS, now=job.fire_at) == []
    assert len(claim_due_jobs(db, leg_types=OTHER_LEGS, now=job.fire_at)) == 1
