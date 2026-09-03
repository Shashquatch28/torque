"""Module 5 — runtime graph execution end-to-end (Blueprint §5.1)."""

from __future__ import annotations

from sqlalchemy import select

from torque.enums import (
    ActionOutcome,
    ActionType,
    CaseEventType,
    CaseStatus,
    LegType,
    PlaybookRunStatus,
)
from torque.execution import StepResult, execute_due_jobs
from torque.execution.runner import execute_due_job
from torque.models import Action, CaseEvent, Playbook, ScheduledJob


def _actions(db, run):
    return db.scalars(select(Action).where(Action.run_id == run.run_id)).all()


def _step_events(db, case):
    return db.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .where(CaseEvent.event_type == CaseEventType.STEP_TRANSITIONED)
        .order_by(CaseEvent.event_seq_id)
    ).all()


def test_first_step_executes_and_advances(db, make_active_run):
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    assert run.active_step_id == "retry_1"
    first_fire = job.fire_at

    [result] = execute_due_jobs(db, leg_types=(LegType.PAYMENT_DEGRADATION,), now=job.fire_at)
    assert result is StepResult.EXECUTED
    db.refresh(run)
    db.refresh(job)
    assert run.active_step_id == "retry_2"  # advanced on on_success
    assert job.fire_at > first_fire  # timer re-armed for the next step
    actions = _actions(db, run)
    assert len(actions) == 1
    assert actions[0].action_type is ActionType.RETRY_PAYMENT
    assert actions[0].outcome is ActionOutcome.SUCCESS
    assert actions[0].run_id == run.run_id


def test_full_run_drains_to_escalation(db, make_active_run, drain_run):
    case, run, _ = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    results = drain_run(run)

    assert StepResult.ESCALATED in results
    db.refresh(run)
    db.refresh(case)
    assert run.status is PlaybookRunStatus.ESCALATED
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN
    # timer removed at terminal.
    assert db.scalars(select(ScheduledJob).where(ScheduledJob.run_id == run.run_id)).first() is None
    # one ESCALATE_HUMAN action fired at the terminal node.
    assert any(a.action_type is ActionType.ESCALATE_HUMAN for a in _actions(db, run))


def test_terminal_non_escalate_exhausts(db, make_active_run, drain_run):
    case, run, _ = make_active_run(
        leg=LegType.B2B_RECEIVABLE, root_cause_code="LIQUIDITY_DELAY_LOW_RISK", context={}
    )
    results = drain_run(run)

    assert StepResult.EXHAUSTED in results
    db.refresh(run)
    db.refresh(case)
    assert run.status is PlaybookRunStatus.COMPLETED
    assert case.status is CaseStatus.EXHAUSTED
    # gentle B2B dunning never escalates to a human.
    assert not any(a.action_type is ActionType.ESCALATE_HUMAN for a in _actions(db, run))


def test_failure_outcome_follows_fallback_edge(db, make_active_run, monkeypatch):
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    monkeypatch.setattr(
        "torque.execution.runner.run_action", lambda ctx: ActionOutcome.FAILED
    )
    execute_due_jobs(db, leg_types=(LegType.PAYMENT_DEGRADATION,), now=job.fire_at)

    db.refresh(run)
    assert run.active_step_id == "retry_2"  # linear ladder: on_failed also advances
    evt = _step_events(db, case)[-1]
    assert evt.payload["edge_condition"] == "on_failed"
    assert evt.payload["outcome"] == "FAILED"


def test_step_transitioned_payload_shape(db, make_active_run, drain_run):
    """U-02 settled (D-091): run attribution + reconstructable previous→outcome→next,
    terminal-safe (to_step_id/edge_condition null at the end)."""
    case, run, _ = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    drain_run(run)
    events = _step_events(db, case)
    assert events, "expected STEP_TRANSITIONED events"
    for e in events:
        assert set(e.payload) == {
            "run_id", "from_step_id", "to_step_id", "edge_condition", "outcome"
        }
        assert e.payload["run_id"] == str(run.run_id)
        assert e.payload["from_step_id"]
    terminal = events[-1]
    assert terminal.payload["to_step_id"] is None
    assert terminal.payload["edge_condition"] is None


def test_each_step_writes_action_executed_event(db, make_active_run, drain_run):
    case, run, _ = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    drain_run(run)
    exec_events = db.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .where(CaseEvent.event_type == CaseEventType.ACTION_EXECUTED)
    ).all()
    # 4-node ladder: retry_1, retry_2, nudge, escalate.
    assert len(exec_events) == 4
    assert {e.payload["action_type"] for e in exec_events} == {
        "RETRY_PAYMENT", "SEND_WHATSAPP", "ESCALATE_HUMAN"
    }


def test_execution_uses_pinned_version_not_latest(db, make_active_run, monkeypatch):
    from copy import deepcopy

    from tests.conftest import VALID_STEPS_GRAPH, VALID_STOPPING_RULES

    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    assert run.playbook_version == 1

    # Publish a v2 of the SAME playbook with a different entry node id.
    v2_graph = deepcopy(VALID_STEPS_GRAPH)  # entry "n1"
    db.add(
        Playbook(
            playbook_id=run.playbook_id,
            version=2,
            leg_type=LegType.PAYMENT_DEGRADATION,
            steps_graph=v2_graph,
            stopping_rules=deepcopy(VALID_STOPPING_RULES),
        )
    )
    db.flush()

    # The run still traverses v1 ("retry_1"/"retry_2"), never v2's "n1".
    execute_due_jobs(db, leg_types=(LegType.PAYMENT_DEGRADATION,), now=job.fire_at)
    db.refresh(run)
    assert run.playbook_version == 1
    assert run.active_step_id == "retry_2"


def test_job_for_terminal_run_is_a_noop(db, make_active_run):
    case, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    run.status = PlaybookRunStatus.COMPLETED
    db.flush()
    result = execute_due_job(db, job, now=job.fire_at)
    assert result is StepResult.NOOP
    assert db.scalars(select(ScheduledJob).where(ScheduledJob.run_id == run.run_id)).first() is None
