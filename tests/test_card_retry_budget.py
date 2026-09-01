"""Blueprint Section 3 - CardRetryBudget: pure pre-retry predicate + schema
invariants (unique per (token, merchant), hard_stop/reason coherence, tenant
scoping)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from torque.compliance import (
    CARD_ATTEMPTS_24H_CAP,
    CARD_ATTEMPTS_30D_CAP,
    card_retry_within_budget,
)
from torque.db.scoped import TenantScope
from torque.enums import HardStopReason
from torque.exceptions import CrossTenantWriteError
from torque.models import CardRetryBudget

# --- pure predicate ------------------------------------------------------


def test_within_budget_true_below_all_caps():
    assert card_retry_within_budget(
        attempts_used_24h=9, attempts_used_30d=34, hard_stop=False
    )


def test_blocked_at_24h_cap():
    assert not card_retry_within_budget(
        attempts_used_24h=CARD_ATTEMPTS_24H_CAP, attempts_used_30d=0, hard_stop=False
    )
    assert card_retry_within_budget(
        attempts_used_24h=CARD_ATTEMPTS_24H_CAP - 1, attempts_used_30d=0, hard_stop=False
    )


def test_blocked_at_30d_cap():
    assert not card_retry_within_budget(
        attempts_used_24h=0, attempts_used_30d=CARD_ATTEMPTS_30D_CAP, hard_stop=False
    )
    assert card_retry_within_budget(
        attempts_used_24h=0, attempts_used_30d=CARD_ATTEMPTS_30D_CAP - 1, hard_stop=False
    )


def test_blocked_when_hard_stop():
    assert not card_retry_within_budget(
        attempts_used_24h=0, attempts_used_30d=0, hard_stop=True
    )


# --- schema invariants ------------------------------------------------


def test_unique_card_token_per_merchant(db, make_merchant):
    m = make_merchant()
    db.add(CardRetryBudget(card_token_hash="tok_A", merchant_id=m.merchant_id))
    db.flush()
    db.add(CardRetryBudget(card_token_hash="tok_A", merchant_id=m.merchant_id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_same_token_different_merchants_ok(db, make_merchant):
    m1, m2 = make_merchant(), make_merchant()
    db.add(CardRetryBudget(card_token_hash="tok_shared", merchant_id=m1.merchant_id))
    db.add(CardRetryBudget(card_token_hash="tok_shared", merchant_id=m2.merchant_id))
    db.flush()


def test_hard_stop_reason_coherence_true_requires_reason(db, make_merchant):
    m = make_merchant()
    db.add(
        CardRetryBudget(
            card_token_hash="tok_hs", merchant_id=m.merchant_id, hard_stop=True
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_hard_stop_reason_coherence_false_forbids_reason(db, make_merchant):
    m = make_merchant()
    db.add(
        CardRetryBudget(
            card_token_hash="tok_hs2",
            merchant_id=m.merchant_id,
            hard_stop=False,
            hard_stop_reason=HardStopReason.NETWORK_HARD_STOP,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_hard_stop_reason_coherence_matching_pairs_ok(db, make_merchant):
    m = make_merchant()
    db.add_all(
        [
            CardRetryBudget(
                card_token_hash="tok_ok1",
                merchant_id=m.merchant_id,
                hard_stop=True,
                hard_stop_reason=HardStopReason.NETWORK_HARD_STOP,
            ),
            CardRetryBudget(
                card_token_hash="tok_ok2",
                merchant_id=m.merchant_id,
                hard_stop=True,
                hard_stop_reason=HardStopReason.INSTRUMENT_NOT_RECURRING_CAPABLE,
            ),
            CardRetryBudget(
                card_token_hash="tok_ok3", merchant_id=m.merchant_id, hard_stop=False
            ),
        ]
    )
    db.flush()


def test_tenant_scoped(db, make_merchant):
    m1, m2 = make_merchant(), make_merchant()
    scope1 = TenantScope(db, m1.merchant_id)
    budget = CardRetryBudget(card_token_hash="tok_scoped")
    scope1.add(budget)
    db.flush()
    assert budget.merchant_id == m1.merchant_id

    scope2 = TenantScope(db, m2.merchant_id)
    with pytest.raises(CrossTenantWriteError):
        scope2.add(CardRetryBudget(card_token_hash="x", merchant_id=m1.merchant_id))
