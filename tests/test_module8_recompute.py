"""Module 8 §8.5 — recompute cadence: case creation, diagnosis completion, and
the daily open-case sweep. Real DB, real ingestion / diagnosis transactions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.enums import CaseStatus, LegType
from torque.ingestion.cases import create_or_attach_case
from torque.models import HumanQueueEntry, RevenueLeakCase
from torque.scoring import compute_recovery_score, recompute_open_cases, score_case
from torque.scoring.score import _ALWAYS_TERMINAL

_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


# --- trigger 1: case creation --------------------------------------


def test_leg1_case_creation_scores_the_case(db, make_merchant, make_event):
    m = make_merchant()
    body = razorpay_payment_body(event="payment.failed", amount_paise=1_240_000)
    ev = make_event(m, type="payment.failed", raw_payload=json.loads(body))
    create_or_attach_case(db, event=ev)

    case = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.source_event_id == ev.event_id)
    ).one()
    assert case.recovery_score is not None
    assert case.recovery_score_updated_at is not None
    assert case.recovery_score_breakdown["leg_type"] == "PAYMENT_DEGRADATION"
    # a case born DETECTED has no playbook yet → the cost floors
    assert case.recovery_score_breakdown["cost_basis"] == "FLOOR_NO_PLAYBOOK"
    # matches a fresh recompute
    assert case.recovery_score == compute_recovery_score(db, case).score


def test_b2b_invoice_attach_rescores_with_new_amount(db, make_case):
    from torque.models import B2BInvoice

    case = make_case(leg=LegType.B2B_RECEIVABLE, amount_at_risk=Decimal("1000.00"), context={})
    score_case(db, case, now=_NOW)
    first = case.recovery_score

    db.add(B2BInvoice(
        merchant_id=case.merchant_id, case_id=case.case_id,
        counterparty_id=case.counterparty_id,
        due_date=(_NOW - timedelta(days=10)).date(), days_overdue=10,
        original_amount=Decimal("5000.00"), outstanding_amount=Decimal("5000.00"),
    ))
    case.amount_at_risk = Decimal("6000.00")
    db.flush()
    score_case(db, case, now=_NOW)
    assert case.recovery_score != first
    assert case.recovery_score == compute_recovery_score(db, case, now=_NOW).score


# --- trigger 2: diagnosis completion -----------------------------


def test_diagnosis_completion_rescores_with_candidate_playbook(
    db, seeded_catalog, make_merchant, make_counterparty, make_event
):
    from torque.diagnosis.engine import diagnose_case
    from torque.models import RevenueLeakCase

    m = make_merchant()
    cp = make_counterparty()
    ev = make_event(m)
    case = RevenueLeakCase(
        merchant_id=m.merchant_id, leg_type=LegType.CHECKOUT_ABANDONMENT,
        source_event_id=ev.event_id, counterparty_id=cp.counterparty_id,
        amount_at_risk=Decimal("2000.00"), status=CaseStatus.DETECTED,
        context={"cart_id": "c", "cart_value": "2000.00",
                 "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT"},
    )
    db.add(case)
    db.flush()
    score_case(db, case, now=_NOW)
    before = dict(case.recovery_score_breakdown)
    assert before["cost_basis"] == "FLOOR_NO_PLAYBOOK"

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.root_cause_code is not None
    # score refreshed inside the diagnosis transaction; cost now has a basis
    assert case.recovery_score_breakdown["cost_basis"] != "FLOOR_NO_PLAYBOOK"
    assert case.recovery_score == compute_recovery_score(db, case).score


# --- trigger 3: daily sweep -------------------------------------


def test_daily_sweep_rescores_open_cases_and_ages_the_bucket(db, make_case):
    case = make_case(
        leg=LegType.SUBSCRIPTION_FAILURE, amount_at_risk=Decimal("9000.00"),
        context={"mandate_id": "m", "mandate_type": "CARD",
                 "billing_cycle": "1", "subscription_id": "s"},
    )
    case.opened_at = _NOW - timedelta(hours=1)
    db.flush()
    score_case(db, case, now=_NOW)
    assert case.recovery_score_breakdown["base_probability"] == "0.65"  # fresh

    # ten days later the same case is stale
    later = _NOW + timedelta(days=10)
    n = recompute_open_cases(db, now=later)
    assert n >= 1
    db.refresh(case)
    assert case.recovery_score_breakdown["base_probability"] == "0.25"


def test_daily_sweep_refreshes_human_queue_priority(db, make_case):
    from torque.coordination import human_queue as HQ

    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.ESCALATED_TO_HUMAN,
        context={"gateway": "razorpay"}, amount_at_risk=Decimal("4000.00"),
    )
    HQ.enqueue(db, case=case, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)
    entry = db.scalars(
        select(HumanQueueEntry).where(HumanQueueEntry.case_id == case.case_id)
    ).one()
    original = entry.priority

    case.amount_at_risk = Decimal("40000.00")  # 10x
    db.flush()
    recompute_open_cases(db, now=_NOW)
    db.refresh(entry)
    db.refresh(case)
    assert entry.priority == case.recovery_score
    assert entry.priority > original


def test_daily_sweep_skips_terminal_and_superseded_cases(db, make_case):
    recovered = make_case(
        leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.RECOVERED,
        context={"gateway": "razorpay"}, amount_at_risk=Decimal("500.00"),
    )
    superseded = make_case(
        leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("500.00"),
    )
    canonical = make_case(
        leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("500.00"),
    )
    superseded.superseded_by_case_id = canonical.case_id
    db.flush()

    recompute_open_cases(db, now=_NOW)
    db.refresh(recovered)
    db.refresh(superseded)
    db.refresh(canonical)
    assert recovered.recovery_score is None       # terminal — never scored
    assert superseded.recovery_score is None      # merged away — never scored
    assert canonical.recovery_score is not None


def test_score_case_is_a_noop_for_terminal_cases(db, make_case):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.CANCELLED,
        context={"gateway": "razorpay"}, amount_at_risk=Decimal("500.00"),
    )
    assert score_case(db, case, now=_NOW) is None
    assert case.recovery_score is None


def test_always_terminal_set_matches_state_machine():
    from torque.state_machine import TERMINAL_STATUSES

    # every leg-independent terminal status is in the sweep's SQL pre-filter
    assert set(_ALWAYS_TERMINAL) <= set(TERMINAL_STATUSES)
