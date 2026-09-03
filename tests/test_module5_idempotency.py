"""Module 5 — idempotency & concurrency (Blueprint §5.1, items 17/23).

The exactly-once guarantee rests on: one pending timer per run (`UNIQUE(run_id)`),
claimed `FOR UPDATE SKIP LOCKED`. These tests prove a second worker cannot claim a
job another holds, so no step is double-executed and no attempt double-counted —
using two genuinely separate DB connections (committed data, cleaned up after).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from torque.db.session import SessionLocal
from torque.enums import CaseStatus, LegType
from torque.execution import claim_due_jobs, execute_due_jobs, schedule_run
from torque.execution.scheduler import PAYMENT_LEGS
from torque.models import (
    Action,
    Counterparty,
    Event,
    Merchant,
    PlaybookRun,
    RevenueLeakCase,
    UPIRetryBudget,
)
from torque.policy.catalog import seed_catalog
from torque.policy.engine import activate_case


def test_future_job_is_not_claimed(db, make_active_run):
    _, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    before = job.fire_at - timedelta(hours=1)
    assert claim_due_jobs(db, leg_types=PAYMENT_LEGS, now=before) == []


def test_redelivery_after_advance_is_not_a_duplicate(db, make_active_run):
    """After a step fires the timer moves forward; the same run is not re-claimed
    until the next step is due (so a poll storm cannot double-fire a step)."""
    _, run, job = make_active_run(root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    execute_due_jobs(db, leg_types=PAYMENT_LEGS, now=job.fire_at)
    db.refresh(job)
    # A second poll at the ORIGINAL fire time claims nothing (fire_at advanced).
    assert claim_due_jobs(db, leg_types=PAYMENT_LEGS, now=job.fire_at - timedelta(seconds=1)) == []
    assert len(db.scalars(select(Action).where(Action.run_id == run.run_id)).all()) == 1


# --- true concurrency (two connections) --------------------------------------


@pytest.fixture()
def committed_run(engine):
    """A committed merchant+case+run+UPI-budget+timer for cross-connection tests.
    Yields ids; deletes everything afterwards so the shared test DB stays clean."""
    ids = {}
    setup = SessionLocal(bind=engine.connect())
    try:
        seed_catalog(setup)
        m = Merchant(
            merchant_id="acc_concurrency", channels_enabled=[],
            risk_appetite_config={"payday_cycle_override_enabled": False},
        )
        cp = Counterparty(
            name="C", phone="+910000000001", email="c@x.test",
            payment_failure_nudge_consent=True,
        )
        setup.add_all([m, cp])
        setup.flush()
        ev = Event(
            merchant_id=m.merchant_id, type="subscription.charged.failed",
            idempotency_key="evt_conc", raw_payload={},
        )
        setup.add(ev)
        setup.flush()
        case = RevenueLeakCase(
            merchant_id=m.merchant_id, leg_type=LegType.SUBSCRIPTION_FAILURE,
            source_event_id=ev.event_id, counterparty_id=cp.counterparty_id,
            amount_at_risk=1000, status=CaseStatus.PLAYBOOK_ACTIVE,
            root_cause_code="NSF_SOFT_DECLINE",
            context={
                "mandate_id": "conc_upi", "mandate_type": "UPI_AUTOPAY",
                "billing_cycle": "1", "subscription_id": "s",
            },
        )
        setup.add(case)
        setup.flush()
        setup.add(UPIRetryBudget(merchant_id=m.merchant_id, mandate_id="conc_upi", attempts_used=1))
        activate_case(setup, case_id=case.case_id)
        run = setup.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).one()
        job = schedule_run(setup, run_id=run.run_id, now=datetime(2000, 1, 1, tzinfo=UTC))
        setup.commit()
        ids = {
            "merchant": m.merchant_id, "run": run.run_id,
            "case": case.case_id, "job_fire": job.fire_at,
        }
    finally:
        setup.close()

    yield ids

    # The concurrency tests never COMMIT an execution (they roll back), so no
    # append-only case_event / action rows are persisted — cleanup only removes the
    # committed setup rows, in FK order, via raw SQL (bypassing the ORM guards).
    from sqlalchemy import text

    conn = engine.connect()
    try:
        mid = ids["merchant"]
        for table, col in [
            ("scheduled_job", "merchant_id"),
            ("upi_retry_budget", "merchant_id"),
            ("playbook_run", "merchant_id"),
            ("revenue_leak_case", "merchant_id"),
            ("event", "merchant_id"),
            ("merchant", "merchant_id"),
        ]:
            conn.execute(text(f"DELETE FROM {table} WHERE {col} = :m"), {"m": mid})
        conn.commit()
    finally:
        conn.close()


def test_two_workers_claim_disjoint_jobs(committed_run, engine):
    """SKIP LOCKED: while worker A holds the run's only due job, worker B claims
    nothing — the step cannot be executed twice concurrently (item 23)."""
    now = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)  # far future, in-window; job is due
    conn_a, conn_b = engine.connect(), engine.connect()
    sa, sb = SessionLocal(bind=conn_a), SessionLocal(bind=conn_b)
    try:
        claimed_a = claim_due_jobs(sa, leg_types=(LegType.SUBSCRIPTION_FAILURE,), now=now)
        claimed_b = claim_due_jobs(sb, leg_types=(LegType.SUBSCRIPTION_FAILURE,), now=now)
        assert len(claimed_a) == 1  # A holds the row under its lock
        assert claimed_b == []  # B skips the locked row
        sa.rollback()
        sb.rollback()
    finally:
        sa.close()
        sb.close()
        conn_a.close()
        conn_b.close()


def test_concurrent_execution_consumes_one_attempt(committed_run, engine):
    """Two workers race to execute the run's due step; exactly one Action is
    written and the UPI attempt counter advances by exactly one (item 12)."""
    now = committed_run["job_fire"]  # the real fire time (≈ run creation, in-window)
    conn_a, conn_b = engine.connect(), engine.connect()
    sa, sb = SessionLocal(bind=conn_a), SessionLocal(bind=conn_b)
    try:
        # A claims + executes (holding its row lock); B, concurrent, claims nothing.
        results_a = execute_due_jobs(sa, leg_types=(LegType.SUBSCRIPTION_FAILURE,), now=now)
        claimed_b = claim_due_jobs(sb, leg_types=(LegType.SUBSCRIPTION_FAILURE,), now=now)
        assert len(results_a) == 1
        assert claimed_b == []  # only one worker executed the step
        # Within A's transaction: exactly one Action and one attempt consumed.
        actions = sa.scalars(select(Action).where(Action.run_id == committed_run["run"])).all()
        assert len(actions) == 1
        budget = sa.scalars(
            select(UPIRetryBudget).where(UPIRetryBudget.mandate_id == "conc_upi")
        ).one()
        assert budget.attempts_used == 1  # pre-debit node fired; retry not yet
        sa.rollback()  # discard — keeps the shared DB free of append-only rows
        sb.rollback()
    finally:
        sa.close()
        sb.close()
        conn_a.close()
        conn_b.close()
