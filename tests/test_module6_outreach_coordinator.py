"""Module 6 — Outreach Coordinator: priority seam, cross-leg quiet period, and
quiet-hours (defer-only) as they flow through the runtime tick.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from torque.coordination.outreach_coordinator import priority
from torque.enums import ActionOutcome, ActionType, BlockReason, CaseEventType, CaseStatus, LegType
from torque.execution import execute_due_jobs
from torque.execution.runner import StepResult
from torque.models import Action, CaseEvent

# --- priority (Module 8 seam — Q-B / D-098 / D-113) ---------------------


def test_priority_seam_delegates_to_module8_recovery_score(db, make_case):
    """The seam is now the real Module 8 score, delegated to
    `torque.scoring.compute_recovery_score` — one implementation of the formula,
    no re-derivation here (D-113). Signature is `(session, case)`."""
    from torque.scoring import compute_recovery_score

    case = make_case(leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
                     amount_at_risk=Decimal("12345.67"))
    assert priority(db, case) == compute_recovery_score(db, case).score
    # PAYMENT_DEGRADATION cold-start 0.55, no playbook yet → cost floors to ₹0.01:
    # 0.55 × 12345.67 ÷ 0.01 = 679_011.85
    assert priority(db, case) == Decimal("679011.8500")


# --- quiet-hours: defer only, never a block, never EXHAUSTED ------------


def test_contact_outside_allowed_hours_defers_without_an_action(db, make_active_run):
    """B2B_LOW_RISK_DUNNING allowed_hours 10:00–18:00 IST. A tick at 08:30 IST
    defers the timer forward — no Action, step not advanced, run not exhausted."""
    case, run, job = make_active_run(
        leg=LegType.B2B_RECEIVABLE, root_cause_code="LIQUIDITY_DELAY_LOW_RISK", context={}
    )
    before_step = run.active_step_id
    out_of_window = datetime(2026, 9, 3, 3, 0, tzinfo=UTC)  # 08:30 IST
    job.fire_at = out_of_window
    db.flush()

    results = execute_due_jobs(db, leg_types=(LegType.B2B_RECEIVABLE,), now=out_of_window)
    assert results == [StepResult.DEFERRED]
    db.refresh(run)
    db.refresh(job)
    assert run.active_step_id == before_step
    assert job.fire_at > out_of_window
    assert db.scalars(select(Action).where(Action.run_id == run.run_id)).all() == []
    db.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE  # not EXHAUSTED


# --- cross-leg 4h quiet period: DEFER + ACTION_BLOCKED, step held ------


def test_cross_leg_quiet_period_writes_blocked_action_and_defers_without_advancing(
    db, make_active_run, make_case, make_merchant, make_counterparty, make_action
):
    m = make_merchant()
    cp = make_counterparty()

    case, run, job = make_active_run(
        merchant=m, counterparty=cp,
        leg=LegType.CHECKOUT_ABANDONMENT, root_cause_code="NO_PAYMENT_METHOD_ATTEMPTED",
        context={
            "cart_id": "cart_xleg", "cart_value": "999.00",
            "drop_stage": "review", "payment_method_attempted": "NONE",
        },
    )
    before_step = run.active_step_id

    # A different-leg (SUBSCRIPTION) outreach for the same counterparty, 1h before.
    other = make_case(
        merchant=m, counterparty=cp, leg=LegType.SUBSCRIPTION_FAILURE,
        status=CaseStatus.PLAYBOOK_ACTIVE,
        context={
            "mandate_id": "x", "mandate_type": "CARD",
            "billing_cycle": "1", "subscription_id": "s",
        },
    )
    act = make_action(case=other, action_type=ActionType.SEND_EMAIL, channel="email")
    act.executed_at = job.fire_at - timedelta(hours=1)
    db.flush()

    results = execute_due_jobs(db, leg_types=(LegType.CHECKOUT_ABANDONMENT,), now=job.fire_at)
    assert results == [StepResult.DEFERRED]

    db.refresh(run)
    db.refresh(job)
    assert run.active_step_id == before_step  # deferred, never skipped

    blocked = db.scalars(
        select(Action)
        .where(Action.run_id == run.run_id)
        .where(Action.outcome == ActionOutcome.BLOCKED_BY_GUARDRAIL)
    ).all()
    assert len(blocked) == 1
    assert blocked[0].block_reason is BlockReason.OUTREACH_COORDINATOR_DEFERRED
    assert blocked[0].executed_at is None

    # the ACTION_BLOCKED CaseEvent is written atomically with the row
    evt = db.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .where(CaseEvent.event_type == CaseEventType.ACTION_BLOCKED)
    ).all()
    assert len(evt) == 1
    assert evt[0].payload["block_reason"] == BlockReason.OUTREACH_COORDINATOR_DEFERRED.value

    # timer pushed to ~quiet_period_end (>= the send + 4h)
    assert job.fire_at >= act.executed_at + timedelta(hours=4)


def test_same_leg_prior_outreach_does_not_defer(
    db, make_active_run, make_case, make_merchant, make_counterparty, make_action
):
    m = make_merchant()
    cp = make_counterparty()
    case, run, job = make_active_run(
        merchant=m, counterparty=cp,
        leg=LegType.CHECKOUT_ABANDONMENT, root_cause_code="NO_PAYMENT_METHOD_ATTEMPTED",
        context={
            "cart_id": "cart_same", "cart_value": "999.00",
            "drop_stage": "review", "payment_method_attempted": "NONE",
        },
    )
    prior = make_case(
        merchant=m, counterparty=cp, leg=LegType.CHECKOUT_ABANDONMENT,
        status=CaseStatus.PLAYBOOK_ACTIVE,
        context={
            "cart_id": "cart_old", "cart_value": "1.00",
            "drop_stage": "review", "payment_method_attempted": "NONE",
        },
    )
    act = make_action(case=prior, action_type=ActionType.SEND_WHATSAPP, channel="whatsapp")
    act.executed_at = job.fire_at - timedelta(hours=1)
    db.flush()

    results = execute_due_jobs(db, leg_types=(LegType.CHECKOUT_ABANDONMENT,), now=job.fire_at)
    # same-leg: the coordinator adds no delay → the step executes
    assert StepResult.EXECUTED in results
    assert db.scalars(
        select(Action)
        .where(Action.run_id == run.run_id)
        .where(Action.outcome == ActionOutcome.SUCCESS)
    ).all()
