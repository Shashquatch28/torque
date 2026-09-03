"""Module 5 corrective-pass regressions — audit findings F-1, F-2, F-6.

F-1: `max_duration` is measured from the first EXECUTED action (D-094), and the
     §4.3 payday substitution applies only to the entry step — so a payday NSF
     retry reaches execution instead of exhausting during the payday wait, without
     weakening `max_duration` for the active span.
F-2: each poll-batch job executes in its own SAVEPOINT — one poison job cannot roll
     back or stall its siblings, and every job's own tick stays all-or-nothing.
F-6: a run whose case is (defensively) superseded never executes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from torque.compliance.retry_rails import IST
from torque.db.scoped import TenantScope
from torque.enums import ActionType, CaseStatus, LegType, PlaybookRunStatus
from torque.execution import execute_due_jobs
from torque.execution.runner import StepResult
from torque.models import Action, MerchantPlaybookConfig, ScheduledJob

_PAYMENT = (LegType.PAYMENT_DEGRADATION,)


def _retry_actions(db, run):
    return db.scalars(
        select(Action)
        .where(Action.run_id == run.run_id)
        .where(Action.action_type == ActionType.RETRY_PAYMENT)
    ).all()


def _executed_actions(db, run):
    return db.scalars(
        select(Action).where(Action.run_id == run.run_id).where(Action.executed_at.is_not(None))
    ).all()


# --- F-1 -----------------------------------------------------------------------


def test_payday_applies_to_entry_step(db, make_active_run):
    """schedule_run arms the entry NSF retry at the payday target (09:00 IST on a
    month-end working day), not the static offset."""
    case, run, job = make_active_run(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        suggested_timing_adjustment="next_month_end_working_day",
        payday=True,
    )
    fire_ist = job.fire_at.astimezone(IST)
    assert fire_ist.strftime("%H:%M") == "09:00"  # payday heuristic fires 09:00 IST
    assert fire_ist.weekday() < 5  # a working day
    assert job.fire_at > run.created_at  # pushed forward to payday


def test_nsf_payday_retry_executes_though_scheduled_beyond_max_duration(db, make_active_run):
    """The flagship F-1 case: the entry retry is scheduled far beyond
    `max_duration_days=14` (a payday can sit ~a month out). It must still EXECUTE —
    previously the run exhausted before the retry fired."""
    case, run, job = make_active_run(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        suggested_timing_adjustment="next_month_end_working_day",
        payday=True,
    )
    # Deterministic in-window fire time, ~16 months after creation (≫ 14 days).
    retry_now = datetime(2027, 1, 15, 6, 30, tzinfo=UTC)  # 12:00 IST, a weekday
    job.fire_at = retry_now
    db.flush()

    results = execute_due_jobs(db, leg_types=_PAYMENT, now=retry_now)
    assert StepResult.EXECUTED in results  # NOT exhausted
    assert StepResult.EXHAUSTED not in results
    db.refresh(run)
    assert run.active_step_id == "nudge"
    assert len(_retry_actions(db, run)) == 1


def test_payday_not_reapplied_to_subsequent_steps(db, make_active_run):
    """After the entry retry, the nudge uses its static 72h offset — NOT another
    payday month-end (the over-application the F-1 fix corrects)."""
    case, run, job = make_active_run(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        suggested_timing_adjustment="next_month_end_working_day",
        payday=True,
    )
    retry_now = datetime(2027, 1, 15, 6, 30, tzinfo=UTC)
    job.fire_at = retry_now
    db.flush()
    execute_due_jobs(db, leg_types=_PAYMENT, now=retry_now)

    db.refresh(job)
    delta = job.fire_at - retry_now
    assert timedelta(hours=72) <= delta < timedelta(days=7)  # 72h offset, not ~a month


def test_max_duration_still_bounds_active_span(db, make_active_run, drain_run):
    """`max_duration` still terminates a run whose ACTIVE execution span exceeds it
    (measured from the first executed action) — proven with a 1-day merchant
    override on a dunning ladder whose 2nd step is 5 days out."""
    case, run, job = make_active_run(
        leg=LegType.B2B_RECEIVABLE, root_cause_code="LIQUIDITY_DELAY_LOW_RISK", context={}
    )
    TenantScope(db, run.merchant_id).add(
        MerchantPlaybookConfig(
            playbook_id=run.playbook_id,
            stopping_rules_override={"max_duration_days": 1},
            enabled=True,
        )
    )
    db.flush()

    results = drain_run(run)
    assert StepResult.EXHAUSTED in results
    db.refresh(run)
    db.refresh(case)
    assert run.status is PlaybookRunStatus.COMPLETED
    assert case.status is CaseStatus.EXHAUSTED
    # Only the first step ran; the 5-days-out second step tripped the 1-day bound.
    assert len(_executed_actions(db, run)) == 1


def test_non_payday_run_unaffected(db, make_active_run, drain_run):
    """A payday-disabled run still executes its full ladder normally."""
    case, run, _ = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER", payday=False)
    results = drain_run(run)
    assert StepResult.ESCALATED in results
    db.refresh(run)
    assert run.status is PlaybookRunStatus.ESCALATED


# --- F-2 -----------------------------------------------------------------------


def _poison(db, make_active_run):
    """A run guaranteed to raise in the tick (its active step id is not a graph
    node → `traversal.node` raises `PlaybookGraphError`)."""
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    run.active_step_id = "does_not_exist"
    db.flush()
    return case, run, job


def test_poison_job_does_not_roll_back_sibling(db, make_active_run):
    """Two due jobs in one poll pass: the healthy one commits its action, the poison
    one's savepoint rolls back — its failure does not undo the sibling (F-2)."""
    good_case, good_run, good_job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    bad_case, bad_run, bad_job = _poison(db, make_active_run)

    now = max(good_job.fire_at, bad_job.fire_at)
    results = execute_due_jobs(db, leg_types=_PAYMENT, now=now)

    assert StepResult.ERROR in results  # the poison job was isolated
    assert any(r in (StepResult.EXECUTED, StepResult.BLOCKED) for r in results)
    # the healthy run advanced and kept its action ...
    db.refresh(good_run)
    assert good_run.active_step_id == "retry_2"
    assert len(_executed_actions(db, good_run)) == 1
    # ... while the poison run is untouched and its timer survives for a re-try.
    db.refresh(bad_run)
    assert bad_run.active_step_id == "does_not_exist"
    assert len(db.scalars(select(Action).where(Action.run_id == bad_run.run_id)).all()) == 0
    bad_timer = db.scalars(
        select(ScheduledJob).where(ScheduledJob.run_id == bad_run.run_id)
    ).first()
    assert bad_timer is not None


def test_poison_job_retryable_without_undoing_sibling(db, make_active_run):
    """A second poll re-attempts the poison job (still ERROR) without re-running or
    undoing the already-advanced healthy job."""
    good_case, good_run, good_job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    bad_case, bad_run, bad_job = _poison(db, make_active_run)

    execute_due_jobs(db, leg_types=_PAYMENT, now=max(good_job.fire_at, bad_job.fire_at))
    db.refresh(good_job)
    # second pass: the healthy job's timer has advanced (not due at the poison's time),
    # so only the poison job is claimable — it errors again, healthy work intact.
    results2 = execute_due_jobs(db, leg_types=_PAYMENT, now=bad_job.fire_at)
    assert results2 == [StepResult.ERROR]
    assert len(_executed_actions(db, good_run)) == 1  # unchanged


def test_per_job_atomicity_partial_writes_roll_back(db, make_active_run, monkeypatch):
    """If a tick raises AFTER writing its Action (patched `_step_event`), the whole
    job — Action, CaseEvent, budget, active_step_id, job row — rolls back as one."""
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    before_step = run.active_step_id

    def _boom(*a, **k):
        raise RuntimeError("injected after action write")

    monkeypatch.setattr("torque.execution.runner._step_event", _boom)
    results = execute_due_jobs(db, leg_types=_PAYMENT, now=job.fire_at)

    assert results == [StepResult.ERROR]
    db.refresh(run)
    assert run.active_step_id == before_step  # no advancement
    assert len(db.scalars(select(Action).where(Action.run_id == run.run_id)).all()) == 0
    timer = db.scalars(select(ScheduledJob).where(ScheduledJob.run_id == run.run_id)).first()
    assert timer is not None


# --- F-6 -----------------------------------------------------------------------


def test_superseded_case_run_does_not_execute(db, make_active_run, make_case):
    """Defence-in-depth: a run whose case became superseded never fires an action;
    the stale timer is dropped."""
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    # Mark the run's case superseded (an anomalous, normally-unreachable state).
    survivor = make_case(merchant=None, leg=LegType.PAYMENT_DEGRADATION)
    case.superseded_by_case_id = survivor.case_id
    db.flush()

    results = execute_due_jobs(db, leg_types=_PAYMENT, now=job.fire_at)
    assert results == [StepResult.NOOP]
    assert len(db.scalars(select(Action).where(Action.run_id == run.run_id)).all()) == 0
    assert db.scalars(select(ScheduledJob).where(ScheduledJob.run_id == run.run_id)).first() is None
