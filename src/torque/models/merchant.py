"""`Merchant` — Blueprint Section 3."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base
from torque.models.mixins import TimestampMixin


class Merchant(Base, TimestampMixin):
    __tablename__ = "merchant"

    # Razorpay merchant ID — an external identifier, not a generated UUID.
    merchant_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # "D2C / SaaS / B2B services / marketplace". Kept as free text at this
    # milestone; a controlled vocabulary can be introduced without a data change.
    business_type: Mapped[str | None] = mapped_column(String(64))
    # "Metro / Tier-2-3" — feeds language/tone calibration in later modules.
    tier: Mapped[str | None] = mapped_column(String(32))
    # e.g. ["whatsapp", "email", "sms"].
    channels_enabled: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # Default max attempts / escalation ceiling, etc.
    risk_appetite_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
