"""Module 6 — the live Outreach Coordinator merge (Blueprint Part A §5 / §4.4).

Two runs for the same `(merchant, counterparty)` whose current step is a
non-terminal outreach action and whose timers are both due, executed in one poll
pass, fold into a single `Action` (with a `multi_case_template`) or the primary
sends and the secondary defers (without one) — never silently dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from torque.db.session import SessionLocal
from torque.enums import ActionOutcome, CaseStatus, LegType
from torque.execution import claim_due_jobs, execute_due_jobs
from torque.execution.runner import StepResult
from torque.execution.scheduler import OTHER_LEGS
from torque.models import Action, ActionCase, ScheduledJob

_B2B = (LegType.B2B_RECEIVABLE,)


def _b2b_run(make_active_run, m, cp, amount):
    return make_active_run(
        merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE,
        root_cause_code="LIQUIDITY_DELAY_LOW_RISK", context={}, amount_at_risk=amount,
    )


def _cart_run(make_active_run, m, cp, seq):
    return make_active_run(
        merchant=m, counterparty=cp, leg=LegType.CHECKOUT_ABANDONMENT,
        root_cause_code="UPI_COLLECT_FRICTION",
        context={
            "cart_id": f"cart_{seq}", "cart_value": "999.00",
            "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
        },
    )


# --- with a multi_case_template: one merged Action ----------------------


def test_two_due_b2b_jobs_fold_into_one_merged_action(
    db, make_active_run, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty()
    c1, r1, j1 = _b2b_run(make_active_run, m, cp, Decimal("1000.00"))
    c2, r2, j2 = _b2b_run(make_active_run, m, cp, Decimal("3000.00"))  # higher → primary
    now = max(j1.fire_at, j2.fire_at)

    results = execute_due_jobs(db, leg_types=_B2B, now=now)
    assert results.count(StepResult.MERGED) == 2

    # exactly one Action, owned by the higher-priority run (c2)
    all_actions = db.scalars(
        select(Action).where(Action.run_id.in_((r1.run_id, r2.run_id)))
    ).all()
    assert len(all_actions) == 1
    action = all_actions[0]
    assert action.run_id == r2.run_id
    assert action.primary_case_id == c2.case_id
    assert action.outcome is ActionOutcome.SUCCESS

    # one ActionCase per case, exact weight conservation, primary flagged
    acs = db.scalars(select(ActionCase).where(ActionCase.action_id == action.action_id)).all()
    assert {ac.case_id for ac in acs} == {c1.case_id, c2.case_id}
    assert sum(ac.credit_weight for ac in acs) == Decimal("1.00000")
    primary_ac = next(ac for ac in acs if ac.is_primary)
    assert primary_ac.case_id == c2.case_id
    assert primary_ac.credit_weight == Decimal("0.75000")  # 3000 / 4000

    # both runs advanced off the entry step; both timers rescheduled forward
    db.refresh(r1)
    db.refresh(r2)
    assert r1.active_step_id == "wa"
    assert r2.active_step_id == "wa"
    for run_id in (r1.run_id, r2.run_id):
        job = db.scalars(select(ScheduledJob).where(ScheduledJob.run_id == run_id)).one()
        assert job.fire_at > now


def test_merge_only_groups_same_counterparty(
    db, make_active_run, make_merchant, make_counterparty
):
    m = make_merchant()
    cp1, cp2 = make_counterparty(), make_counterparty()
    _c1, r1, j1 = _b2b_run(make_active_run, m, cp1, Decimal("1000.00"))
    _c2, r2, j2 = _b2b_run(make_active_run, m, cp2, Decimal("1000.00"))
    now = max(j1.fire_at, j2.fire_at)

    results = execute_due_jobs(db, leg_types=_B2B, now=now)
    assert StepResult.MERGED not in results
    # each run got its own solo Action
    for run_id in (r1.run_id, r2.run_id):
        assert len(db.scalars(select(Action).where(Action.run_id == run_id)).all()) == 1


# --- without a multi_case_template: primary sends, secondary defers -----


def test_no_multi_template_primary_sends_secondary_defers(
    db, make_active_run, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty()
    c1, r1, j1 = _cart_run(make_active_run, m, cp, 1)
    c2, r2, j2 = _cart_run(make_active_run, m, cp, 2)
    # equal amounts → primary is decided by case_id ordering; find which is primary
    now = max(j1.fire_at, j2.fire_at)

    results = execute_due_jobs(db, leg_types=(LegType.CHECKOUT_ABANDONMENT,), now=now)
    assert StepResult.DEFERRED in results

    runs = {r1.run_id: r1, r2.run_id: r2}
    sent = [
        a for a in db.scalars(select(Action).where(Action.run_id.in_(runs))).all()
    ]
    successes = [a for a in sent if a.outcome is ActionOutcome.SUCCESS]
    deferred = [a for a in sent if a.outcome is ActionOutcome.BLOCKED_BY_GUARDRAIL]
    assert len(successes) == 1  # the primary sent its single-case message
    assert len(deferred) == 1  # the secondary was deferred, not dropped
    from torque.enums import BlockReason

    assert deferred[0].block_reason is BlockReason.OUTREACH_COORDINATOR_DEFERRED

    primary_run_id = successes[0].run_id
    secondary_run_id = deferred[0].run_id
    assert primary_run_id != secondary_run_id

    db.refresh(runs[secondary_run_id])
    assert runs[secondary_run_id].active_step_id == "wa"  # NOT advanced — deferred
    sec_job = db.scalars(
        select(ScheduledJob).where(ScheduledJob.run_id == secondary_run_id)
    ).one()
    assert sec_job.fire_at > now  # its timer moved forward


# --- concurrency: two workers cannot both fire the co-located pair -----


def test_second_worker_claims_nothing_while_the_merge_pass_holds_the_pair(engine):
    """A merge always operates on jobs already claimed under this pass's
    `FOR UPDATE SKIP LOCKED` — a concurrent worker sees neither, so it cannot
    independently fire either message (item 23)."""
    from torque.execution import schedule_run
    from torque.models import Counterparty, Event, Merchant, PlaybookRun, RevenueLeakCase
    from torque.policy.catalog import seed_catalog
    from torque.policy.engine import activate_case

    setup = SessionLocal(bind=engine.connect())
    ids = {}
    try:
        seed_catalog(setup)
        m = Merchant(merchant_id="acc_merge_conc", channels_enabled=[], risk_appetite_config={})
        cp = Counterparty(name="C", phone="+910000009999", email="mc@x.test",
                          payment_failure_nudge_consent=True, whatsapp_opt_in=True)
        setup.add_all([m, cp])
        setup.flush()
        run_ids = []
        for i in range(2):
            ev = Event(merchant_id=m.merchant_id, type="invoice.overdue",
                       idempotency_key=f"evt_mc_{i}", raw_payload={})
            setup.add(ev)
            setup.flush()
            case = RevenueLeakCase(
                merchant_id=m.merchant_id, leg_type=LegType.B2B_RECEIVABLE,
                source_event_id=ev.event_id, counterparty_id=cp.counterparty_id,
                amount_at_risk=1000 + i, status=CaseStatus.PLAYBOOK_ACTIVE,
                root_cause_code="LIQUIDITY_DELAY_LOW_RISK", context={},
            )
            setup.add(case)
            setup.flush()
            activate_case(setup, case_id=case.case_id)
            run = setup.scalars(
                select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)
            ).one()
            schedule_run(setup, run_id=run.run_id, now=datetime(2000, 1, 1, tzinfo=UTC))
            run_ids.append(run.run_id)
        setup.commit()
        ids = {"merchant": m.merchant_id, "runs": run_ids}
    finally:
        setup.close()

    now = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    conn_a, conn_b = engine.connect(), engine.connect()
    sa, sb = SessionLocal(bind=conn_a), SessionLocal(bind=conn_b)
    try:
        results_a = execute_due_jobs(sa, leg_types=OTHER_LEGS, now=now)
        claimed_b = claim_due_jobs(sb, leg_types=OTHER_LEGS, now=now)
        assert results_a.count(StepResult.MERGED) == 2
        assert claimed_b == []  # B cannot touch either job
        actions_a = sa.scalars(
            select(Action).where(Action.run_id.in_(ids["runs"]))
        ).all()
        assert len(actions_a) == 1  # a single merged Action, not two
        sa.rollback()
        sb.rollback()
    finally:
        sa.close()
        sb.close()
        conn_a.close()
        conn_b.close()
        cleanup = engine.connect()
        try:
            from sqlalchemy import text

            tbls = ("scheduled_job", "playbook_run", "revenue_leak_case", "event", "merchant")
            for table in tbls:
                cleanup.execute(
                    text(f"DELETE FROM {table} WHERE merchant_id = :m"), {"m": ids["merchant"]}
                )
            cleanup.commit()
        finally:
            cleanup.close()
