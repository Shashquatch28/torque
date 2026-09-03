"""Module 5 — tenant isolation across the execution path (Blueprint §2.1)."""

from __future__ import annotations

from sqlalchemy import select

from torque.enums import LegType
from torque.execution import execute_due_jobs
from torque.models import CardRetryBudget, Event


def test_retry_consumes_only_the_case_merchants_budget(db, make_active_run, make_merchant):
    """Merchant A and B share a card token; executing A's card retry advances A's
    budget only — B's identically-keyed budget is never touched. (Card has no
    execution-window gate, so this is time-deterministic.)"""
    shared = "tok_shared_x"
    a = make_merchant(risk_appetite_config={"payday_cycle_override_enabled": False})
    b = make_merchant(risk_appetite_config={"payday_cycle_override_enabled": False})
    db.add(CardRetryBudget(
        merchant_id=a.merchant_id, card_token_hash=shared,
        attempts_used_24h=1, attempts_used_30d=1, hard_stop=False,
    ))
    db.add(CardRetryBudget(
        merchant_id=b.merchant_id, card_token_hash=shared,
        attempts_used_24h=1, attempts_used_30d=1, hard_stop=False,
    ))
    db.flush()

    case, run, job = make_active_run(merchant=a, root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    ev = db.get(Event, case.source_event_id)
    ev.raw_payload = {"payload": {"payment": {"entity": {"token_id": shared}}}}
    db.flush()

    # Entry step is retry_1 → executing it consumes exactly one card attempt.
    execute_due_jobs(db, leg_types=(LegType.PAYMENT_DEGRADATION,), now=job.fire_at)

    a_budget = db.scalars(
        select(CardRetryBudget)
        .where(CardRetryBudget.merchant_id == a.merchant_id)
        .where(CardRetryBudget.card_token_hash == shared)
    ).one()
    b_budget = db.scalars(
        select(CardRetryBudget)
        .where(CardRetryBudget.merchant_id == b.merchant_id)
        .where(CardRetryBudget.card_token_hash == shared)
    ).one()
    assert a_budget.attempts_used_24h == 2  # A's retry consumed one attempt
    assert b_budget.attempts_used_24h == 1  # B untouched


def test_poller_processes_each_job_in_its_own_merchant_scope(db, make_active_run, make_merchant):
    """A single poll pass spanning two merchants' jobs executes each against its
    own case/run — no cross-merchant lookup."""
    a = make_merchant(risk_appetite_config={"payday_cycle_override_enabled": False})
    b = make_merchant(risk_appetite_config={"payday_cycle_override_enabled": False})
    ca, ra, ja = make_active_run(merchant=a, root_cause_code="ISSUER_SOFT_DECLINE_OTHER")
    cb, rb, jb = make_active_run(merchant=b, root_cause_code="ISSUER_SOFT_DECLINE_OTHER")

    now = max(ja.fire_at, jb.fire_at)
    execute_due_jobs(db, leg_types=(LegType.PAYMENT_DEGRADATION,), now=now)

    from torque.models import Action

    a_actions = db.scalars(select(Action).where(Action.run_id == ra.run_id)).all()
    b_actions = db.scalars(select(Action).where(Action.run_id == rb.run_id)).all()
    assert len(a_actions) == 1 and a_actions[0].merchant_id == a.merchant_id
    assert len(b_actions) == 1 and b_actions[0].merchant_id == b.merchant_id
