"""Decision K - the four retry-budget demo scenarios must be representable with
the Milestone 2 schema, and the pure predicates must return the expected
block/allow for each. (The one-click demo *injectors* are Module 10; here we
only prove schema + predicates can carry the scenarios.)"""

from __future__ import annotations

from datetime import date

from torque.compliance import (
    card_retry_within_budget,
    nach_retry_eligible,
    tier_for,
    upi_attempt_gate_open,
)
from torque.config import get_policy
from torque.enums import ClearingCycleStatus, HardStopReason, MacTier, Network
from torque.models import (
    CardRetryBudget,
    NACHRetryPolicy,
    UPIRetryBudget,
)


def test_scenario_1_tier1_hard_stop_blocks_card_retry(db, make_merchant):
    """MAC 03 is Tier 1; the CardRetryBudget carries hard_stop / NETWORK_HARD_STOP
    and the pre-retry predicate refuses the retry even though volume is low."""
    assert tier_for(db, Network.MASTERCARD, "03") is MacTier.TIER_1_HARD_STOP

    m = make_merchant()
    budget = CardRetryBudget(
        card_token_hash="tok_tier1",
        merchant_id=m.merchant_id,
        attempts_used_24h=1,
        attempts_used_30d=1,
        hard_stop=True,
        hard_stop_reason=HardStopReason.NETWORK_HARD_STOP,
    )
    db.add(budget)
    db.flush()

    assert not card_retry_within_budget(
        attempts_used_24h=budget.attempts_used_24h,
        attempts_used_30d=budget.attempts_used_30d,
        hard_stop=budget.hard_stop,
    )
    assert budget.hard_stop_reason is HardStopReason.NETWORK_HARD_STOP  # "stop all contact"


def test_scenario_2_tier3_routes_to_new_payment_method(db, make_merchant):
    """MAC 40 is Tier 3; hard_stop is set but the reason is
    INSTRUMENT_NOT_RECURRING_CAPABLE - a different downstream action
    (request a new payment method, not silence)."""
    assert tier_for(db, Network.MASTERCARD, "40") is MacTier.TIER_3_INSTRUMENT_DEAD

    m = make_merchant()
    budget = CardRetryBudget(
        card_token_hash="tok_tier3",
        merchant_id=m.merchant_id,
        attempts_used_24h=1,
        attempts_used_30d=1,
        hard_stop=True,
        hard_stop_reason=HardStopReason.INSTRUMENT_NOT_RECURRING_CAPABLE,
    )
    db.add(budget)
    db.flush()

    assert not card_retry_within_budget(
        attempts_used_24h=1, attempts_used_30d=1, hard_stop=True
    )
    assert budget.hard_stop_reason is HardStopReason.INSTRUMENT_NOT_RECURRING_CAPABLE


def test_scenario_3_upi_autopay_hits_3_retry_cap(db, make_merchant):
    m = make_merchant()
    budget = UPIRetryBudget(
        merchant_id=m.merchant_id, mandate_id="mand_capped", attempts_used=3
    )
    db.add(budget)
    db.flush()

    assert not upi_attempt_gate_open(
        attempts_used=budget.attempts_used,
        mandate_cancelled_at=budget.mandate_cancelled_at,
    )
    # one attempt earlier the gate was still open
    assert upi_attempt_gate_open(attempts_used=2, mandate_cancelled_at=None)


def test_scenario_4_nach_approaching_self_imposed_ceiling(db, make_merchant):
    ceiling = get_policy().nach_representment_ceiling_default  # 3
    m = make_merchant()
    policy = NACHRetryPolicy(
        merchant_id=m.merchant_id,
        mandate_id="mand_ceiling",
        clearing_cycle_status=ClearingCycleStatus.RETURNED,
        dishonour_count_this_fy=3,
        retry_eligible_after=date(2026, 8, 1),
    )
    db.add(policy)
    db.flush()

    # at the ceiling -> not eligible
    assert not nach_retry_eligible(
        clearing_cycle_status=policy.clearing_cycle_status,
        dishonour_count_this_fy=policy.dishonour_count_this_fy,
        retry_eligible_after=policy.retry_eligible_after,
        ceiling=ceiling,
        as_of=date(2026, 9, 1),
    )
    # one representment earlier it was still eligible
    assert nach_retry_eligible(
        clearing_cycle_status=ClearingCycleStatus.RETURNED,
        dishonour_count_this_fy=2,
        retry_eligible_after=date(2026, 8, 1),
        ceiling=ceiling,
        as_of=date(2026, 9, 1),
    )
