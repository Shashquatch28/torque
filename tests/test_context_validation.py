"""Blueprint Section 3 — RevenueLeakCase.context is a strict typed model per
leg_type, validated at the ORM boundary. Nothing untyped is ever persisted."""

from __future__ import annotations

import pytest

from torque.contexts import validate_context
from torque.enums import LegType
from torque.exceptions import ContextValidationError
from torque.models import RevenueLeakCase


def _case(m, cp, ev, leg, ctx):
    return RevenueLeakCase(
        merchant_id=m.merchant_id,
        leg_type=leg,
        source_event_id=ev.event_id,
        counterparty_id=cp.counterparty_id,
        amount_at_risk=1000,
        context=ctx,
    )


def test_valid_payment_degradation_context_normalised():
    out = validate_context(
        LegType.PAYMENT_DEGRADATION,
        {"decline_code": "5C", "gateway": "razorpay", "retry_count": 1, "is_hard_decline": False},
    )
    assert out["gateway"] == "razorpay"


def test_extra_key_rejected():
    with pytest.raises(ContextValidationError):
        validate_context(
            LegType.PAYMENT_DEGRADATION,
            {"gateway": "razorpay", "unexpected": "nope"},
        )


def test_subscription_context_rejects_pre_debit_notified_at():
    # The field was deliberately removed — per-attempt tracking is a table now.
    with pytest.raises(ContextValidationError):
        validate_context(
            LegType.SUBSCRIPTION_FAILURE,
            {
                "mandate_id": "mand_1",
                "mandate_type": "UPI_AUTOPAY",
                "billing_cycle": "monthly",
                "subscription_id": "sub_1",
                "pre_debit_notified_at": "2026-09-01T00:00:00Z",
            },
        )


def test_b2b_receivable_takes_no_context():
    assert validate_context(LegType.B2B_RECEIVABLE, {}) == {}
    with pytest.raises(ContextValidationError):
        validate_context(LegType.B2B_RECEIVABLE, {"anything": 1})


def test_guard_rejects_bad_context_on_flush(db, make_merchant, make_counterparty, make_event):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    # decline_code alone, no required `gateway` -> guard should reject at flush.
    db.add(_case(m, cp, ev, LegType.PAYMENT_DEGRADATION, {"decline_code": "5C"}))
    with pytest.raises(ContextValidationError):
        db.flush()


def test_guard_normalises_good_context_on_flush(
    db, make_merchant, make_counterparty, make_event
):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    case = _case(
        m,
        cp,
        ev,
        LegType.CHECKOUT_ABANDONMENT,
        {
            "cart_id": "cart_9",
            "cart_value": "1999.00",
            "drop_stage": "vpa_entry",
            "payment_method_attempted": "UPI_COLLECT",
        },
    )
    db.add(case)
    db.flush()
    assert case.context["payment_method_attempted"] == "UPI_COLLECT"
