"""Milestone 7b — ingestion-time `CardRetryBudget` seeding (Blueprint §2.7)."""

from __future__ import annotations

import json

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.ingestion.buffer import resolve_buffered_event
from torque.ingestion.cases import create_or_attach_case
from torque.models import CardRetryBudget, UPIRetryBudget


def _event(make_event, m, **body):
    return make_event(
        m, type="payment.failed", raw_payload=json.loads(razorpay_payment_body(**body))
    )


def _budgets(db, merchant_id):
    return list(
        db.scalars(select(CardRetryBudget).where(CardRetryBudget.merchant_id == merchant_id))
    )


def test_card_payment_seeds_budget_at_one(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="card", token_id="token_ABC", card_id=None)
    create_or_attach_case(db, event=ev)

    (budget,) = _budgets(db, m.merchant_id)
    assert budget.card_token_hash == "token_ABC"
    assert budget.attempts_used_24h == 1
    assert budget.attempts_used_30d == 1
    assert budget.hard_stop is False
    assert budget.hard_stop_reason is None


def test_falls_back_to_card_id_when_no_token(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="card", token_id=None, card_id="card_XYZ")
    create_or_attach_case(db, event=ev)
    (budget,) = _budgets(db, m.merchant_id)
    assert budget.card_token_hash == "card_XYZ"


def test_redelivery_does_not_double_count(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="card", token_id="token_IDEMP")
    resolve_buffered_event(db, event_id=ev.event_id)
    resolve_buffered_event(db, event_id=ev.event_id)
    budgets = _budgets(db, m.merchant_id)
    assert len(budgets) == 1
    assert budgets[0].attempts_used_24h == 1


def test_no_instrument_reference_seeds_nothing(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="card", token_id=None, card_id=None)
    create_or_attach_case(db, event=ev)
    assert _budgets(db, m.merchant_id) == []


def test_non_card_payment_seeds_no_card_or_upi_budget(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="upi", token_id=None, card_id=None)
    create_or_attach_case(db, event=ev)
    assert _budgets(db, m.merchant_id) == []
    upi = db.scalars(
        select(UPIRetryBudget).where(UPIRetryBudget.merchant_id == m.merchant_id)
    ).all()
    assert upi == []  # UPI AutoPay seeding is a Leg-3 concern, not this path
