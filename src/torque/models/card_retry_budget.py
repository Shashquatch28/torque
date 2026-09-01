"""`CardRetryBudget` — Mastercard dual-window volume limit. Blueprint Section 3.

**Applies only when the payment instrument is a card** — never consulted for
NACH or UPI AutoPay. Enforcement (the pre-retry check) is Module 5; this
milestone provides the table plus the pure predicate
`torque.compliance.retry_rails.card_retry_within_budget`.

`hard_stop` is `true` only for `TIER_1_HARD_STOP` and `TIER_3_INSTRUMENT_DEAD`
MACs, and `hard_stop_reason` then says which downstream action applies
(stop all contact vs. request a new payment method). The two move together —
enforced by the `hard_stop_reason_coherent` check constraint.

Milestone 2 does NOT implement the ingestion-time counter seeding/upsert
(counters start at 1 from the originating decline, same transaction as the
case) — that is Module 2 Section 2.7.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import HardStopReason
from torque.models.mixins import TimestampMixin, uuid_pk


class CardRetryBudget(Base, TenantScoped, TimestampMixin):
    __tablename__ = "card_retry_budget"
    __table_args__ = (
        UniqueConstraint("card_token_hash", "merchant_id"),
        CheckConstraint("attempts_used_24h >= 0", name="attempts_used_24h_non_negative"),
        CheckConstraint("attempts_used_30d >= 0", name="attempts_used_30d_non_negative"),
        CheckConstraint(
            "(hard_stop = false AND hard_stop_reason IS NULL) OR "
            "(hard_stop = true AND hard_stop_reason IS NOT NULL)",
            name="hard_stop_reason_coherent",
        ),
    )

    budget_id: Mapped[uuid.UUID] = uuid_pk()
    # Tokenised card identifier — NEVER a raw PAN.
    card_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    attempts_used_24h: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts_used_30d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hard_stop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hard_stop_reason: Mapped[HardStopReason | None] = mapped_column(
        PgEnum(HardStopReason, name="hard_stop_reason", create_type=False)
    )
