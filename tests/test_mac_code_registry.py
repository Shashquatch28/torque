"""Blueprint Section 3 - MacCodeRegistry: exactly the 13 locked seed rows,
global scope, and the pure `tier_for` lookup."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from torque.compliance import tier_for
from torque.db.scoped import TenantScope
from torque.enums import MacTier, Network
from torque.exceptions import NonTenantModelError
from torque.models import MacCodeRegistry

EXPECTED = {
    "03": MacTier.TIER_1_HARD_STOP,
    "21": MacTier.TIER_1_HARD_STOP,
    "5C": MacTier.TIER_2_CAPPED_RETRY,
    "9G": MacTier.TIER_2_CAPPED_RETRY,
    "40": MacTier.TIER_3_INSTRUMENT_DEAD,
    "41": MacTier.TIER_3_INSTRUMENT_DEAD,
    "24": MacTier.TIMED_RETRY,
    "25": MacTier.TIMED_RETRY,
    "26": MacTier.TIMED_RETRY,
    "27": MacTier.TIMED_RETRY,
    "28": MacTier.TIMED_RETRY,
    "29": MacTier.TIMED_RETRY,
    "30": MacTier.TIMED_RETRY,
}

# A sample of the Part E item 1 "explicitly NOT yet seeded" set.
UNSEEDED_SAMPLE = ["01", "02", "04", "05", "51", "52", "91", "96"]


def test_seed_has_exactly_13_rows(db):
    assert db.scalar(select(func.count()).select_from(MacCodeRegistry)) == 13


def test_seed_is_mastercard_only(db):
    networks = set(db.scalars(select(MacCodeRegistry.network)).all())
    assert networks == {Network.MASTERCARD}


@pytest.mark.parametrize(("code", "tier"), EXPECTED.items())
def test_seed_tiers_are_correct(db, code, tier):
    assert tier_for(db, Network.MASTERCARD, code) is tier


def test_unseeded_codes_are_absent(db):
    for code in UNSEEDED_SAMPLE:
        assert tier_for(db, Network.MASTERCARD, code) is None


def test_no_visa_rows_seeded(db):
    assert tier_for(db, Network.VISA, "03") is None
    assert db.scalar(
        select(func.count())
        .select_from(MacCodeRegistry)
        .where(MacCodeRegistry.network == Network.VISA)
    ) == 0


def test_tier_for_returns_none_on_miss(db):
    assert tier_for(db, Network.MASTERCARD, "ZZ") is None


def test_mac_code_registry_is_global_scope(db, make_merchant):
    scope = TenantScope(db, make_merchant().merchant_id)
    with pytest.raises(NonTenantModelError):
        scope.select(MacCodeRegistry)
