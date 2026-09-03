"""Module 8 §8.4 / §8.7 — the authoritative score
`(probability × amount_at_risk) ÷ cost`, its exact Decimal arithmetic, the
structured explainability, and ranking behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from torque.enums import CaseStatus, LegType
from torque.scoring import compute_recovery_score

_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _payment_case(make_case, *, amount, **kw):
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay"},
        amount_at_risk=Decimal(amount),
        **kw,
    )


# --- the formula, exactly ---------------------------------------------


def test_score_is_probability_times_amount_over_cost_exactly(db, make_case):
    # PAYMENT_DEGRADATION cold-start 0.55, no history, no playbook → cost floors
    # to 0.01.  0.55 × 12400 ÷ 0.01 = 682000.0000
    case = _payment_case(make_case, amount="12400.00")
    rs = compute_recovery_score(db, case, now=_NOW)
    assert rs.base_probability == Decimal("0.55")
    assert rs.probability == Decimal("0.55")
    assert rs.amount_at_risk == Decimal("12400.00")
    assert rs.effective_cost == Decimal("0.01")
    assert rs.score == Decimal("682000.0000")
    # the exposed pieces reconstruct the score
    assert (rs.probability * rs.amount_at_risk) / rs.effective_cost == rs.score


def test_score_uses_exact_decimal_not_float(db, make_case):
    case = _payment_case(make_case, amount="0.03")
    rs = compute_recovery_score(db, case, now=_NOW)
    # 0.55 * 0.03 / 0.01 = 1.65 — exact, no float drift
    assert rs.score == Decimal("1.6500")


def test_warm_start_history_moves_the_score(db, make_case, make_merchant, make_counterparty):
    m = make_merchant()
    cp_strong = make_counterparty()
    cp_poor = make_counterparty()
    from torque.models import MerchantCounterparty

    db.add(MerchantCounterparty(
        merchant_id=m.merchant_id, counterparty_id=cp_strong.counterparty_id,
        promise_keeping_rate=1.0,
    ))
    db.add(MerchantCounterparty(
        merchant_id=m.merchant_id, counterparty_id=cp_poor.counterparty_id,
        promise_keeping_rate=0.0,
    ))
    db.flush()

    strong = _payment_case(make_case, amount="1000.00", merchant=m, counterparty=cp_strong)
    poor = _payment_case(make_case, amount="1000.00", merchant=m, counterparty=cp_poor)

    rs_strong = compute_recovery_score(db, strong, now=_NOW)
    rs_poor = compute_recovery_score(db, poor, now=_NOW)

    assert rs_strong.warm_start_applied is True
    assert rs_strong.warm_start_multiplier == Decimal("1.3")
    assert rs_poor.warm_start_multiplier == Decimal("0.5")
    # same base, same amount, same cost → score scales with the multiplier
    assert rs_strong.probability == Decimal("0.55") * Decimal("1.3")
    assert rs_poor.probability == Decimal("0.55") * Decimal("0.5")
    assert rs_strong.score > rs_poor.score


def test_negative_amount_is_rejected(db, make_case):
    from torque.exceptions import RecoveryScoreError

    case = _payment_case(make_case, amount="1000.00")
    case.amount_at_risk = Decimal("-1.00")
    import pytest

    with pytest.raises(RecoveryScoreError):
        compute_recovery_score(db, case, now=_NOW)


def test_zero_amount_scores_zero_not_error(db, make_case):
    case = _payment_case(make_case, amount="0.00")
    rs = compute_recovery_score(db, case, now=_NOW)
    assert rs.score == Decimal("0.0000")


def test_deterministic_same_inputs_same_score(db, make_case):
    case = _payment_case(make_case, amount="777.00")
    a = compute_recovery_score(db, case, now=_NOW)
    b = compute_recovery_score(db, case, now=_NOW)
    assert a.score == b.score
    assert a.to_dict() == b.to_dict()


# --- explainability (§8.7) -----------------------------------------


def test_explain_exposes_the_four_numbers_and_a_why(db, make_case):
    case = _payment_case(make_case, amount="12400.00")
    rs = compute_recovery_score(db, case, now=_NOW)
    ex = rs.explain()
    assert ex["probability"] == "0.55"
    assert ex["amount_at_risk"] == "12400.00"
    assert ex["expected_cost"] == "0.01"
    assert ex["priority_score"] == "682000"
    assert Decimal(ex["priority_score"]) == rs.score
    assert "Payment degradation" in ex["why"]
    assert any("55% benchmark" in line for line in ex["why"])


def test_explain_names_the_next_intervention_channel(db, seeded_catalog, make_case):
    case = make_case(
        leg=LegType.CHECKOUT_ABANDONMENT,
        status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code="UPI_COLLECT_FRICTION",
        context={
            "cart_id": "x", "cart_value": "500.00",
            "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
        },
    )
    rs = compute_recovery_score(db, case, now=_NOW)
    assert any("Next intervention: whatsapp" in line for line in rs.explain()["why"])


def test_breakdown_roundtrips_through_to_dict(db, make_case):
    case = _payment_case(make_case, amount="500.00")
    rs = compute_recovery_score(db, case, now=_NOW)
    d = rs.to_dict()
    assert d["score"] == str(rs.score)
    assert d["cost_basis"] == "FLOOR_NO_PLAYBOOK"
    assert d["leg_type"] == "PAYMENT_DEGRADATION"
    assert "explain" in d


# --- ranking / tradeoffs -----------------------------------------


def test_ranking_amount_dominates_when_probability_and_cost_equal(db, make_case):
    small = _payment_case(make_case, amount="100.00")
    big = _payment_case(make_case, amount="90000.00")
    s = compute_recovery_score(db, small, now=_NOW).score
    b = compute_recovery_score(db, big, now=_NOW).score
    assert b > s


def test_probability_vs_amount_tradeoff(db, make_case):
    # A fresh subscription failure (0.65) on ₹8,000 vs a stale one (0.25) on
    # ₹18,000. Same cost basis (no playbook). 0.65*8000 = 5200 vs 0.25*18000 =
    # 4500 → the fresher, smaller case wins on expected recovery.
    fresh = make_case(
        leg=LegType.SUBSCRIPTION_FAILURE, amount_at_risk=Decimal("8000.00"),
        context={"mandate_id": "m1", "mandate_type": "CARD",
                 "billing_cycle": "1", "subscription_id": "s1"},
    )
    stale = make_case(
        leg=LegType.SUBSCRIPTION_FAILURE, amount_at_risk=Decimal("18000.00"),
        context={"mandate_id": "m2", "mandate_type": "CARD",
                 "billing_cycle": "1", "subscription_id": "s2"},
    )
    stale.opened_at = _NOW - timedelta(days=20)
    db.flush()
    rs_fresh = compute_recovery_score(db, fresh, now=_NOW)
    rs_stale = compute_recovery_score(db, stale, now=_NOW)
    assert rs_fresh.base_probability == Decimal("0.65")
    assert rs_stale.base_probability == Decimal("0.25")
    assert rs_fresh.score > rs_stale.score


def test_cost_sensitive_ranking(db, seeded_catalog, make_active_run, make_case):
    # Two same-leg diagnosed cases, equal amount. One's next step is a free
    # RETRY_PAYMENT (cost floors), the other's is a priced WhatsApp send. The
    # cheaper next intervention ranks higher for the same expected recovery.
    cheap_case, _r, _j = make_active_run(
        leg=LegType.PAYMENT_DEGRADATION, root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        amount_at_risk=Decimal("5000.00"),
    )
    pricey_case, run2, _j2 = make_active_run(
        leg=LegType.PAYMENT_DEGRADATION, root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        amount_at_risk=Decimal("5000.00"),
    )
    run2.active_step_id = "nudge"  # SEND_WHATSAPP step of PLAYBOOK_NSF_RETRY
    db.flush()

    cheap = compute_recovery_score(db, cheap_case, now=_NOW)
    pricey = compute_recovery_score(db, pricey_case, now=_NOW)
    assert cheap.effective_cost == Decimal("0.01")
    assert pricey.effective_cost == Decimal("0.8850")
    assert cheap.score > pricey.score
