"""Module 8 — correctness guarantees: tenant isolation, terminal-case exclusion,
safe handling of bad monetary values, no division by zero, determinism.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from torque.enums import CaseStatus, LegType
from torque.exceptions import RecoveryScoreError
from torque.scoring import compute_recovery_score, recompute_open_cases, score_case

_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


# --- tenant isolation ---------------------------------------------


def test_promise_keeping_history_is_read_only_from_the_case_merchant(
    db, make_case, make_merchant, make_counterparty
):
    from torque.models import MerchantCounterparty

    a, b = make_merchant(), make_merchant()
    cp = make_counterparty()
    # Merchant A has STRONG history with this counterparty; merchant B has POOR.
    db.add(MerchantCounterparty(
        merchant_id=a.merchant_id, counterparty_id=cp.counterparty_id, promise_keeping_rate=1.0,
    ))
    db.add(MerchantCounterparty(
        merchant_id=b.merchant_id, counterparty_id=cp.counterparty_id, promise_keeping_rate=0.0,
    ))
    db.flush()

    case_a = make_case(merchant=a, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
                       context={"gateway": "razorpay"}, amount_at_risk=Decimal("1000.00"))
    case_b = make_case(merchant=b, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
                       context={"gateway": "razorpay"}, amount_at_risk=Decimal("1000.00"))

    rs_a = compute_recovery_score(db, case_a, now=_NOW)
    rs_b = compute_recovery_score(db, case_b, now=_NOW)
    assert rs_a.promise_keeping_rate == 1.0
    assert rs_b.promise_keeping_rate == 0.0
    assert rs_a.warm_start_multiplier == Decimal("1.3")
    assert rs_b.warm_start_multiplier == Decimal("0.5")


def test_daily_sweep_is_tenant_scopable(db, make_case, make_merchant):
    a, b = make_merchant(), make_merchant()
    ca = make_case(merchant=a, leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"})
    cb = make_case(merchant=b, leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"})

    n = recompute_open_cases(db, merchant_id=a.merchant_id, now=_NOW)
    assert n == 1
    db.refresh(ca)
    db.refresh(cb)
    assert ca.recovery_score is not None
    assert cb.recovery_score is None  # merchant B untouched


# --- terminal / closed cases excluded -------------------------


@pytest.mark.parametrize(
    "status",
    [CaseStatus.RECOVERED, CaseStatus.EXHAUSTED, CaseStatus.CANCELLED, CaseStatus.WRITTEN_OFF],
)
def test_score_case_skips_every_terminal_status(db, make_case, status):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION, status=status,
        context={"gateway": "razorpay"}, amount_at_risk=Decimal("1000.00"),
    )
    assert score_case(db, case, now=_NOW) is None
    assert case.recovery_score is None


def test_non_b2b_partially_recovered_is_terminal_and_skipped(db, make_case):
    case = make_case(
        leg=LegType.SUBSCRIPTION_FAILURE, status=CaseStatus.PARTIALLY_RECOVERED,
        amount_at_risk=Decimal("1000.00"),
        context={"mandate_id": "m", "mandate_type": "CARD",
                 "billing_cycle": "1", "subscription_id": "s"},
    )
    assert score_case(db, case, now=_NOW) is None


def test_b2b_partially_recovered_is_open_and_still_scored(db, make_case):
    case = make_case(
        leg=LegType.B2B_RECEIVABLE, status=CaseStatus.PARTIALLY_RECOVERED,
        amount_at_risk=Decimal("1000.00"), context={},
    )
    rs = score_case(db, case, now=_NOW)
    assert rs is not None
    assert case.recovery_score is not None


# --- bad monetary values / no division by zero ---------------


def test_negative_amount_at_risk_is_rejected_safely(db, make_case):
    case = make_case(leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
                     amount_at_risk=Decimal("100.00"))
    case.amount_at_risk = Decimal("-0.01")
    with pytest.raises(RecoveryScoreError):
        compute_recovery_score(db, case, now=_NOW)


def test_none_amount_at_risk_scores_zero(db, make_case):
    case = make_case(leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
                     amount_at_risk=Decimal("100.00"))
    # simulate a corrupt in-memory row
    case.amount_at_risk = None
    rs = compute_recovery_score(db, case, now=_NOW)
    assert rs.score == Decimal("0.0000")


def test_cost_never_divides_by_zero_even_with_a_zero_rate_card(db, make_active_run):
    from torque.models import ChannelRateCard

    case, run, _job = make_active_run(
        leg=LegType.CHECKOUT_ABANDONMENT, root_cause_code="UPI_COLLECT_FRICTION",
        amount_at_risk=Decimal("1000.00"),
        context={"cart_id": "z", "cart_value": "1000.00",
                 "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT"},
    )
    db.execute(ChannelRateCard.__table__.update().values(rate_per_unit=Decimal("0")))
    db.flush()
    rs = compute_recovery_score(db, case, now=_NOW)
    assert rs.effective_cost > 0
    assert rs.score == (rs.probability * rs.amount_at_risk) / rs.effective_cost


def test_all_channel_rate_cards_missing_still_scores(db, make_active_run):
    from torque.models import ChannelRateCard

    case, run, _job = make_active_run(
        leg=LegType.CHECKOUT_ABANDONMENT, root_cause_code="UPI_COLLECT_FRICTION",
        amount_at_risk=Decimal("1000.00"),
        context={"cart_id": "z2", "cart_value": "1000.00",
                 "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT"},
    )
    db.execute(ChannelRateCard.__table__.delete())
    db.flush()
    rs = compute_recovery_score(db, case, now=_NOW)
    assert rs.effective_cost == Decimal("0.01")
    assert rs.score > 0


# --- determinism -----------------------------------------------


def test_repeated_scoring_is_byte_identical(db, make_case):
    case = make_case(leg=LegType.B2B_RECEIVABLE, amount_at_risk=Decimal("3333.33"), context={})
    runs = [compute_recovery_score(db, case, now=_NOW).to_dict() for _ in range(5)]
    assert all(r == runs[0] for r in runs)


def test_score_case_persists_exactly_what_compute_returns(db, make_case):
    case = make_case(leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
                     amount_at_risk=Decimal("4242.00"))
    rs = score_case(db, case, now=_NOW)
    assert case.recovery_score == rs.score
    assert case.recovery_score_breakdown == rs.to_dict()
    assert case.recovery_score_updated_at == _NOW
