"""Blueprint Section 3 / Module 12 Phase 1 - ChannelRateCard: seed = exactly
whatsapp/email/sms, global scope, freeform String PK, non-negative rates."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from torque.db.scoped import TenantScope
from torque.exceptions import NonTenantModelError
from torque.models import ChannelRateCard


def test_seed_is_exactly_the_three_channels(db):
    channels = set(db.scalars(select(ChannelRateCard.channel)).all())
    assert channels == {"whatsapp", "email", "sms"}


def test_seed_row_count_is_three(db):
    assert db.scalar(select(func.count()).select_from(ChannelRateCard)) == 3


def test_seed_rates_are_non_negative(db):
    for rate in db.scalars(select(ChannelRateCard.rate_per_unit)).all():
        assert rate >= 0


def test_channel_is_primary_key(db):
    db.add(ChannelRateCard(channel="whatsapp", rate_per_unit=Decimal("1.0")))
    with pytest.raises(IntegrityError):
        db.flush()


def test_rate_per_unit_non_negative_check(db):
    db.add(ChannelRateCard(channel="voice", rate_per_unit=Decimal("-0.01")))
    with pytest.raises(IntegrityError):
        db.flush()


def test_channel_rate_card_is_global_scope(db, make_merchant):
    scope = TenantScope(db, make_merchant().merchant_id)
    with pytest.raises(NonTenantModelError):
        scope.select(ChannelRateCard)


def test_unscoped_read_reaches_rate_card(db, make_merchant):
    scope = TenantScope(db, make_merchant().merchant_id)
    rows = scope.unscoped().query(ChannelRateCard).all()
    assert len(rows) == 3
