"""`ChannelRateCard` - Blueprint Section 3 / Module 12 Phase 1.

Static config seeding `Action.cost`. Demo rates are seeded so cost arithmetic is
correct even though actual demo spend is $0 (test-tier delivery).

Global scope - NOT tenant-scoped (R3): a channel's unit rate is the same for
every merchant. `channel` is a freeform `String` primary key (decision D) - no
channel enum. Seeded channels: `whatsapp`, `email`, `sms` only.

This milestone provides the table + seed. Consumption (`Action.cost`, Module 8's
cost term) is Modules 5 / 8.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base
from torque.models.mixins import TimestampMixin


class ChannelRateCard(Base, TimestampMixin):
    __tablename__ = "channel_rate_card"
    __table_args__ = (
        CheckConstraint("rate_per_unit >= 0", name="rate_per_unit_non_negative"),
    )

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Rs per message/unit.
    rate_per_unit: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
