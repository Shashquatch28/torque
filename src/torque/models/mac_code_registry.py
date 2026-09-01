"""`MacCodeRegistry` — network-directive classification. Blueprint Section 3.

A static config table mapping every network decline-advice code to one of four
behaviour tiers. The four-tier *architecture* is locked; the *code-to-tier
mapping* is an empirically-populated, updatable list (Decision M).

Global scope — NOT tenant-scoped (confirmed R3): the same Mastercard/Visa code
means the same thing for every merchant.

Milestone 2 seeds ONLY the 13 locked rows (migration 0006). The larger unseeded
set and the Visa equivalents are Part E item 1 / a Module 5 pre-production
checklist item — do not add them here. The "unseeded code -> default
TIER_2_CAPPED_RETRY + flag a CaseEvent" fallback is Module 5 (Section 5.3);
`torque.compliance.mac_registry.tier_for` returns ``None`` on a miss and leaves
that decision to the caller.
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base
from torque.enums import MacTier, Network
from torque.models.mixins import TimestampMixin


class MacCodeRegistry(Base, TimestampMixin):
    __tablename__ = "mac_code_registry"

    network: Mapped[Network] = mapped_column(
        PgEnum(Network, name="network", create_type=False), primary_key=True
    )
    mac_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    tier: Mapped[MacTier] = mapped_column(
        PgEnum(MacTier, name="mac_tier", create_type=False), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
