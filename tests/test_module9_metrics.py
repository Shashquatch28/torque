"""Module 9 §9.1/§9.2 — core recovery metrics: revenue at risk, recovered
amount, recovery rate, case counts, unresolved amount, zero handling, exact
Decimal arithmetic, by-leg / by-outcome / over-time breakdowns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.module9_helpers import add_action, add_invoice, set_recovery, set_status
from torque.enums import ActionType, CaseStatus, LegType, RecoveryType
from torque.reporting import metrics
from torque.reporting.metrics import ReportWindow

_A = RecoveryType.AGENT_ASSISTED
_S = RecoveryType.SELF_RECOVERED


def _pd_case(make_case, m, *, amount, **kw):
    return make_case(
        merchant=m, leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay"}, amount_at_risk=Decimal(str(amount)), **kw,
    )


_SUB_CTX = {"mandate_id": "x", "mandate_type": "CARD", "billing_cycle": "1", "subscription_id": "s"}


def _b2b_case(make_case, m, *, amount):
    return make_case(
        merchant=m, leg=LegType.B2B_RECEIVABLE, context={},
        amount_at_risk=Decimal(str(amount)),
    )


# --- summary --------------------------------------------------------


def test_summary_zero_cases_is_all_zero_no_error(db, make_merchant):
    m = make_merchant()
    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.case_count == 0
    assert s.revenue_at_risk == Decimal("0.00")
    assert s.recovered_amount == Decimal("0.00")
    assert s.recovery_rate == Decimal("0")
    assert s.amount_recovery_rate == Decimal("0")
    assert s.cost_efficiency_ratio is None


def test_summary_headline_numbers(db, make_merchant, make_case):
    m = make_merchant()
    r1 = _pd_case(make_case, m, amount="5000.00")
    r2 = _pd_case(make_case, m, amount="3000.00")
    self_paid = _pd_case(make_case, m, amount="2000.00")
    open_case = _pd_case(make_case, m, amount="1500.00")  # DETECTED
    exhausted = _pd_case(make_case, m, amount="800.00")

    set_recovery(db, r1, recovery_type=_A, amount="5000.00")
    set_recovery(db, r2, recovery_type=_A, amount="3000.00")
    set_recovery(db, self_paid, recovery_type=_S, amount="2000.00", status=CaseStatus.CANCELLED)
    set_status(db, exhausted, CaseStatus.EXHAUSTED)

    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.case_count == 5
    # revenue at risk = Σ amount_at_risk (non-B2B)
    assert s.revenue_at_risk == Decimal("12300.00")
    # recovered = Torque-credited only (self-paid excluded)
    assert s.recovered_amount == Decimal("8000.00")
    assert s.self_recovered_amount == Decimal("2000.00")
    assert s.recovered_case_count == 2
    assert s.self_recovered_case_count == 1
    assert s.exhausted_case_count == 1
    # unresolved = open + exhausted → open_case (1500) + exhausted (800)
    assert s.unresolved_case_count == 2
    assert s.unresolved_amount == Decimal("2300.00")
    # recovery rate = recovered cases / total = 2/5
    assert s.recovery_rate == Decimal("0.4000")
    # amount recovery rate = 8000 / 12300
    assert s.amount_recovery_rate == Decimal("0.6504")
    assert open_case.status is CaseStatus.DETECTED


def test_summary_uses_exact_decimal(db, make_merchant, make_case):
    m = make_merchant()
    a = _pd_case(make_case, m, amount="1234.56")
    _pd_case(make_case, m, amount="2345.67")  # non-recovered, in revenue_at_risk
    set_recovery(db, a, recovery_type=_A, amount="1234.56")
    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.revenue_at_risk == Decimal("3580.23")
    assert s.recovered_amount == Decimal("1234.56")
    assert s.amount_recovery_rate == (Decimal("1234.56") / Decimal("3580.23")).quantize(
        Decimal("0.0001")
    )


def test_b2b_revenue_at_risk_uses_original_invoice_amount_not_residual(
    db, make_merchant, make_case
):
    m = make_merchant()
    case = _b2b_case(make_case, m, amount="0.00")
    add_invoice(db, case, original="40000.00", outstanding="0.00")
    # Module 7 leaves amount_at_risk at 0 after a full single-payment settlement;
    # the report must still show the ₹40,000 that was at risk.
    set_recovery(db, case, recovery_type=_A, amount="40000.00")
    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.revenue_at_risk == Decimal("40000.00")
    assert s.recovered_amount == Decimal("40000.00")
    assert s.amount_recovery_rate == Decimal("1.0000")


def test_b2b_partial_recovery_counts_banked_amount_but_not_as_recovered_case(
    db, make_merchant, make_case
):
    m = make_merchant()
    case = _b2b_case(make_case, m, amount="6000.00")
    add_invoice(db, case, original="10000.00", outstanding="6000.00")
    set_recovery(
        db, case, recovery_type=_A, amount="4000.00",
        status=CaseStatus.PARTIALLY_RECOVERED, closed_at=None,
    )
    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.revenue_at_risk == Decimal("10000.00")     # original
    assert s.recovered_amount == Decimal("4000.00")      # banked partial counts
    assert s.recovered_case_count == 0                   # still open, not "recovered"
    assert s.partially_recovered_case_count == 1
    assert s.unresolved_case_count == 1                  # B2B partial keeps dunning
    assert s.unresolved_amount == Decimal("6000.00")     # current residual


# --- by leg (§9.1) -------------------------------------------------


def test_recovery_by_leg(db, make_merchant, make_case):
    m = make_merchant()
    pd1 = _pd_case(make_case, m, amount="5000.00")
    pd2 = _pd_case(make_case, m, amount="5000.00")
    sub = make_case(
        merchant=m, leg=LegType.SUBSCRIPTION_FAILURE,
        amount_at_risk=Decimal("9000.00"), context=dict(_SUB_CTX),
    )
    set_recovery(db, pd1, recovery_type=_A, amount="5000.00")
    set_recovery(db, sub, recovery_type=_A, amount="9000.00")

    rows = {r.leg_type: r for r in metrics.recovery_by_leg(db, m.merchant_id)}
    assert rows["PAYMENT_DEGRADATION"].cases_attempted == 2
    assert rows["PAYMENT_DEGRADATION"].cases_recovered == 1
    assert rows["PAYMENT_DEGRADATION"].revenue_at_risk == Decimal("10000.00")
    assert rows["PAYMENT_DEGRADATION"].recovered_amount == Decimal("5000.00")
    assert rows["PAYMENT_DEGRADATION"].recovery_rate == Decimal("0.5000")
    assert rows["SUBSCRIPTION_FAILURE"].cases_recovered == 1
    assert rows["SUBSCRIPTION_FAILURE"].amount_recovery_rate == Decimal("1.0000")
    assert pd2.status is CaseStatus.DETECTED

    # by-leg amount totals reconcile with the summary
    s = metrics.recovery_summary(db, m.merchant_id)
    assert sum(r.recovered_amount for r in rows.values()) == s.recovered_amount
    assert sum(r.revenue_at_risk for r in rows.values()) == s.revenue_at_risk


# --- by recovery type / outcome (§9.2) --------------------------


def test_recovery_by_recovery_type(db, make_merchant, make_case):
    m = make_merchant()
    a = _pd_case(make_case, m, amount="1000.00")
    amb = _pd_case(make_case, m, amount="2000.00")
    slf = _pd_case(make_case, m, amount="3000.00")
    unatt = _pd_case(make_case, m, amount="4000.00")  # never reconciled
    set_recovery(db, a, recovery_type=_A, amount="1000.00")
    set_recovery(db, amb, recovery_type=RecoveryType.AMBIGUOUS, amount="2000.00")
    set_recovery(db, slf, recovery_type=_S, amount="3000.00", status=CaseStatus.CANCELLED)

    rows = {r.recovery_type: r for r in metrics.recovery_by_recovery_type(db, m.merchant_id)}
    assert rows["AGENT_ASSISTED"].recovered_amount == Decimal("1000.00")
    assert rows["AMBIGUOUS"].recovered_amount == Decimal("2000.00")
    assert rows["SELF_RECOVERED"].recovered_amount == Decimal("3000.00")
    assert rows["UNATTRIBUTED"].case_count == 1
    assert unatt.recovery_type is None


# --- recovery over time (§9.2 / D-119) --------------------------


def test_recovery_over_time_day_buckets(db, make_merchant, make_case):
    m = make_merchant()
    d1 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    d2 = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    c1 = _pd_case(make_case, m, amount="1000.00")
    c2 = _pd_case(make_case, m, amount="2000.00")
    c3 = _pd_case(make_case, m, amount="500.00")
    set_recovery(db, c1, recovery_type=_A, amount="1000.00", closed_at=d1)
    set_recovery(db, c2, recovery_type=_A, amount="2000.00", closed_at=d1)
    set_recovery(db, c3, recovery_type=_A, amount="500.00", closed_at=d2)

    buckets = metrics.recovery_over_time(db, m.merchant_id, bucket="day")
    assert len(buckets) == 2
    assert buckets[0].bucket_start.date() == d1.date()
    assert buckets[0].recovered_case_count == 2
    assert buckets[0].recovered_amount == Decimal("3000.00")
    assert buckets[1].recovered_amount == Decimal("500.00")


def test_recovery_over_time_window_is_half_open_no_double_count(db, make_merchant, make_case):
    m = make_merchant()
    boundary = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)
    before = _pd_case(make_case, m, amount="1000.00")
    at = _pd_case(make_case, m, amount="2000.00")
    set_recovery(db, before, recovery_type=_A, amount="1000.00",
                 closed_at=datetime(2026, 9, 1, 23, 59, tzinfo=UTC))
    set_recovery(db, at, recovery_type=_A, amount="2000.00", closed_at=boundary)

    left = metrics.recovery_over_time(
        db, m.merchant_id, window=ReportWindow(end=boundary), bucket="day"
    )
    right = metrics.recovery_over_time(
        db, m.merchant_id, window=ReportWindow(start=boundary), bucket="day"
    )
    assert sum(b.recovered_amount for b in left) == Decimal("1000.00")
    assert sum(b.recovered_amount for b in right) == Decimal("2000.00")


def test_over_time_excludes_self_recovered_and_open(db, make_merchant, make_case):
    m = make_merchant()
    slf = _pd_case(make_case, m, amount="1000.00")
    open_partial = make_case(
        merchant=m, leg=LegType.B2B_RECEIVABLE, context={}, amount_at_risk=Decimal("500.00")
    )
    add_invoice(db, open_partial, original="1000.00", outstanding="500.00")
    set_recovery(db, slf, recovery_type=_S, amount="1000.00", status=CaseStatus.CANCELLED,
                 closed_at=datetime(2026, 9, 1, tzinfo=UTC))
    set_recovery(db, open_partial, recovery_type=_A, amount="500.00",
                 status=CaseStatus.PARTIALLY_RECOVERED, closed_at=None)
    assert metrics.recovery_over_time(db, m.merchant_id) == []


def test_over_time_rejects_bad_bucket(db, make_merchant):
    import pytest

    m = make_merchant()
    with pytest.raises(ValueError, match="bucket"):
        metrics.recovery_over_time(db, m.merchant_id, bucket="fortnight")


# --- cost efficiency (§9.1) --------------------------------------


def test_cost_efficiency_ratio(db, make_merchant, make_case):
    m = make_merchant()
    c = _pd_case(make_case, m, amount="10000.00")
    add_action(db, c, action_type=ActionType.SEND_WHATSAPP, cost="2.50")
    add_action(db, c, action_type=ActionType.SEND_EMAIL, cost="0.50")
    set_recovery(db, c, recovery_type=_A, amount="10000.00")
    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.total_action_cost == Decimal("3.00")
    assert s.cost_efficiency_ratio == (Decimal("10000") / Decimal("3")).quantize(Decimal("0.0001"))
