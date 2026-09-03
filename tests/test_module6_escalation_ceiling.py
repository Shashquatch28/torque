"""Module 6 §6.3 — escalation-ceiling enforcement.

When a `PlaybookRun` accumulates `stopping_rules.escalation_ceiling` unsuccessful
attempts (blocked / failed / no-response — Q-D), **Module 6** (not Module 5)
transitions the case to `ESCALATED_TO_HUMAN`, sets the run `ESCALATED`, enqueues
the case for human pickup, and drops the timer — before any doomed further
action, and never in addition to a graph-terminal `ESCALATE_HUMAN`.
"""

from __future__ import annotations

from sqlalchemy import select

from torque.enums import (
    ActionOutcome,
    CaseEventType,
    CaseStatus,
    LegType,
    PlaybookRunStatus,
)
from torque.execution.runner import StepResult
from torque.models import CaseEvent, HumanQueueEntry, ScheduledJob

_PAYMENT = (LegType.PAYMENT_DEGRADATION,)


def _status_changes_to_escalated(db, case):
    return [
        e
        for e in db.scalars(
            select(CaseEvent)
            .where(CaseEvent.case_id == case.case_id)
            .where(CaseEvent.event_type == CaseEventType.STATUS_CHANGED)
            .order_by(CaseEvent.event_seq_id)
        ).all()
        if e.payload["to_status"] == CaseStatus.ESCALATED_TO_HUMAN.value
    ]


def test_ceiling_reached_escalates_to_human_once(db, make_active_run, drain_run, monkeypatch):
    """GENERIC_SOFT_RETRY: ceiling=2, max_attempts=4. Every action FAILs → the run
    trips the ceiling on the 3rd tick (2 failures banked) before `nudge`/`escalate`
    ever run."""
    monkeypatch.setattr(
        "torque.execution.runner.run_action", lambda ctx: ActionOutcome.FAILED
    )
    case, run, _ = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    results = drain_run(run)

    assert StepResult.ESCALATED_CEILING in results
    assert StepResult.ESCALATED not in results  # the graph terminal never ran
    db.refresh(run)
    db.refresh(case)
    assert run.status is PlaybookRunStatus.ESCALATED
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN
    assert run.active_step_id == "nudge"  # stopped at the step it was about to run

    # exactly one transition, and it is the ceiling's
    changes = _status_changes_to_escalated(db, case)
    assert len(changes) == 1
    assert changes[0].payload["trigger"] == "escalation_ceiling"

    # timer gone; the case is queued for a human with the ceiling reason
    assert db.scalars(select(ScheduledJob).where(ScheduledJob.run_id == run.run_id)).first() is None
    entries = db.scalars(
        select(HumanQueueEntry).where(HumanQueueEntry.case_id == case.case_id)
    ).all()
    assert len(entries) == 1
    from torque.coordination.human_queue import HumanQueueReason

    assert entries[0].reason == str(HumanQueueReason.ESCALATION_CEILING)


def test_only_two_failed_actions_are_written_before_escalation(
    db, make_active_run, drain_run, monkeypatch
):
    monkeypatch.setattr(
        "torque.execution.runner.run_action", lambda ctx: ActionOutcome.FAILED
    )
    case, run, _ = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    drain_run(run)
    from torque.models import Action

    acts = db.scalars(select(Action).where(Action.run_id == run.run_id)).all()
    assert len(acts) == 2
    assert all(a.outcome is ActionOutcome.FAILED for a in acts)


def test_blocked_actions_also_count_toward_the_ceiling(
    db, make_active_run, drain_run, make_counterparty
):
    """PLAYBOOK_SUGGEST_UPI_INTENT: ceiling=1. The WhatsApp step blocks
    (no opt-in) → 1 unsuccessful → the run escalates on the next tick, never
    reaching the email step."""
    cp = make_counterparty(whatsapp_opt_in=False)
    case, run, _ = make_active_run(
        leg=LegType.CHECKOUT_ABANDONMENT,
        root_cause_code="UPI_COLLECT_FRICTION",
        counterparty=cp,
        wa_template=False,
        context={
            "cart_id": "cart_ceiling", "cart_value": "1999.00",
            "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
        },
    )
    results = drain_run(run, legs=(LegType.CHECKOUT_ABANDONMENT,))
    assert StepResult.BLOCKED in results
    assert StepResult.ESCALATED_CEILING in results
    db.refresh(run)
    db.refresh(case)
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN
    assert run.status is PlaybookRunStatus.ESCALATED
    assert run.active_step_id == "email"  # stopped before the email step


def test_ceiling_not_reached_runs_normally(db, make_active_run, drain_run):
    """All actions succeed → 0 unsuccessful → the ceiling never fires; the run
    drains to its graph `ESCALATE_HUMAN` terminal as before (StepResult.ESCALATED,
    not ESCALATED_CEILING)."""
    case, run, _ = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    results = drain_run(run)
    assert StepResult.ESCALATED in results
    assert StepResult.ESCALATED_CEILING not in results
    db.refresh(run)
    assert run.status is PlaybookRunStatus.ESCALATED
    # the graph-terminal escalation does NOT enqueue inline (a later sweep would).
    assert db.scalars(
        select(HumanQueueEntry).where(HumanQueueEntry.case_id == case.case_id)
    ).first() is None


def test_sweep_picks_up_a_graph_terminal_escalation(db, make_active_run, drain_run):
    case, run, _ = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    drain_run(run)
    db.refresh(case)
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN
    from torque.coordination.human_queue import sweep_escalated_to_human

    swept = sweep_escalated_to_human(db, run.merchant_id)
    assert {e.case_id for e in swept} == {case.case_id}
