"""Milestone 8 — rail-specific retry-budget seeding for Leg 3 (§2.7 / Part A §3 / D-072)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from tests.conftest import razorpay_subscription_body
from torque.enums import ClearingCycleStatus
from torque.ingestion.subscription import (
    create_subscription_case,
    resolve_subscription_buffered_event,
)
from torque.models import CardRetryBudget, Event, NACHRetryPolicy, UPIRetryBudget


def _payload(**kw) -> dict:
    return json.loads(razorpay_subscription_body(**kw))


def _event(make_event, m, **body):
    return make_event(
        m,
        type="subscription.charged.failed",
        raw_payload=_payload(event="subscription.charged.failed", **body),
    )


def _upi(db, mid):
    return list(db.scalars(select(UPIRetryBudget).where(UPIRetryBudget.merchant_id == mid)))


def _nach(db, mid):
    return list(db.scalars(select(NACHRetryPolicy).where(NACHRetryPolicy.merchant_id == mid)))


def _card(db, mid):
    return list(db.scalars(select(CardRetryBudget).where(CardRetryBudget.merchant_id == mid)))


def test_upi_autopay_seeds_upi_retry_budget_only(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="upi", token_id="tok_upi")
    create_subscription_case(db, event=ev)

    (budget,) = _upi(db, m.merchant_id)
    assert budget.mandate_id == "tok_upi"
    assert budget.attempts_used == 1
    assert budget.hard_cap == 3
    assert budget.mandate_cancelled_at is None
    assert _nach(db, m.merchant_id) == []
    assert _card(db, m.merchant_id) == []


def test_upi_seeding_is_idempotent_on_redelivery(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="upi", token_id="tok_idem")
    resolve_subscription_buffered_event(db, event_id=ev.event_id)
    resolve_subscription_buffered_event(db, event_id=ev.event_id)
    budgets = _upi(db, m.merchant_id)
    assert len(budgets) == 1 and budgets[0].attempts_used == 1


def test_nach_seeds_nach_retry_policy_only(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="emandate", token_id="tok_nach")
    create_subscription_case(db, event=ev)

    (policy,) = _nach(db, m.merchant_id)
    assert policy.mandate_id == "tok_nach"
    assert policy.clearing_cycle_status is ClearingCycleStatus.RETURNED
    assert policy.dishonour_count_this_fy == 1
    assert policy.return_reason_code is None
    assert policy.retry_eligible_after is None
    assert _upi(db, m.merchant_id) == []
    assert _card(db, m.merchant_id) == []


def test_nach_seeding_is_idempotent(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="emandate", token_id="tok_nach_idem")
    resolve_subscription_buffered_event(db, event_id=ev.event_id)
    resolve_subscription_buffered_event(db, event_id=ev.event_id)
    policies = _nach(db, m.merchant_id)
    assert len(policies) == 1 and policies[0].dishonour_count_this_fy == 1


def test_card_mandate_reuses_the_card_retry_budget_seeder(db, make_merchant, make_event):
    m = make_merchant()
    ev = _event(make_event, m, method="card", token_id="tok_card")
    create_subscription_case(db, event=ev)

    (budget,) = _card(db, m.merchant_id)
    assert budget.card_token_hash == "tok_card"
    assert budget.attempts_used_24h == 1
    assert _upi(db, m.merchant_id) == []
    assert _nach(db, m.merchant_id) == []


def test_no_mandate_id_seeds_no_rail_budget(db, make_merchant, make_event):
    m = make_merchant()
    body = _payload(event="subscription.charged.failed", method="upi")
    body["payload"]["payment"]["entity"].pop("token_id", None)
    body["payload"]["subscription"]["entity"].pop("id", None)  # mandate_id -> ""
    ev = make_event(m, type="subscription.charged.failed", raw_payload=body)
    create_subscription_case(db, event=ev)
    assert _upi(db, m.merchant_id) == []
    assert _nach(db, m.merchant_id) == []


def test_subscription_id_is_never_used_as_the_mandate_id(db, make_merchant, make_event):
    # A UPI subscription failure with a subscription id but NO token: the
    # mandate is unknown -> mandate_id is empty, no UPIRetryBudget row (the
    # blueprint keeps mandate_id and subscription_id distinct; UPIRetryBudget is
    # per-mandate, not per-subscription).
    from sqlalchemy import select

    from torque.models import RevenueLeakCase

    m = make_merchant()
    body = _payload(event="subscription.charged.failed", method="upi", subscription_id="sub_only")
    body["payload"]["payment"]["entity"].pop("token_id", None)
    ev = make_event(m, type="subscription.charged.failed", raw_payload=body)
    create_subscription_case(db, event=ev)

    case = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()
    assert case.context["mandate_id"] == ""
    assert case.context["subscription_id"] == "sub_only"  # still captured, separately
    assert _upi(db, m.merchant_id) == []


def test_seeding_is_tenant_isolated(db, make_merchant, make_event):
    a, b = make_merchant(), make_merchant()
    create_subscription_case(db, event=_event(make_event, a, method="upi", token_id="tok_a"))
    assert len(_upi(db, a.merchant_id)) == 1
    assert _upi(db, b.merchant_id) == []


def test_failure_mid_seed_rolls_everything_back(db, make_merchant, make_event, monkeypatch):
    import torque.ingestion.subscription as sub_mod

    m = make_merchant()
    ev = _event(make_event, m, method="upi", token_id="tok_boom")

    def _boom(*a, **k):
        raise RuntimeError("seed failed")

    monkeypatch.setattr(sub_mod, "_seed_upi_retry_budget", _boom)

    savepoint = db.begin_nested()
    with pytest.raises(RuntimeError):
        resolve_subscription_buffered_event(db, event_id=ev.event_id)
    savepoint.rollback()

    from torque.models import RevenueLeakCase

    assert db.scalars(select(RevenueLeakCase)).all() == []
    assert _upi(db, m.merchant_id) == []
    assert db.get(Event, ev.event_id).processed is False
