"""`PaymentLink` - lifecycle of a Razorpay payment link. Blueprint Section 3.

Module 7 reads `status` to decide `AGENT_ASSISTED` vs `SELF_RECOVERED` - "the
single most important attribution mechanism in the system".

* `link_id` is Razorpay's `plink_...` id (external identifier - no generated
  UUID).
* `action_id` is NULLABLE (decision D10): Module 2 ingests `payment_link.*`
  webhooks broadly for reconciliation, including links that originated outside
  Torque. An unattributed link has `action_id = NULL` - Torque does NOT invent a
  synthetic `Action` for it, and Module 7 can still distinguish Torque-attributed
  recovery from SELF_RECOVERED / AMBIGUOUS.
* Webhook-driven `status` / `amount_paid` / `paid_at` transitions are Module 2/7
  runtime work - not enforced here.

Coherence: `(status = 'paid') = (paid_at IS NOT NULL)` - a biconditional in both
directions (same enum/detail-field pattern as `action.executed_at_matches_outcome`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import PaymentLinkStatus
from torque.models.mixins import TimestampMixin


class PaymentLink(Base, TenantScoped, TimestampMixin):
    __tablename__ = "payment_link"
    __table_args__ = (
        CheckConstraint("amount_paid >= 0", name="amount_paid_non_negative"),
        CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL)",
            name="paid_status_matches_paid_at",
        ),
    )

    # Razorpay plink_... id.
    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    # NULLABLE - externally-originated / unattributed links (decision D10).
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("action.action_id"), nullable=True, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=False, index=True
    )

    status: Mapped[PaymentLinkStatus] = mapped_column(
        # PaymentLinkStatus is the one enum whose member names differ from their
        # values ('issued' vs 'ISSUED'); the Postgres type (created in 0001) uses
        # the lowercase VALUES, so bind/read by value here.
        PgEnum(
            PaymentLinkStatus,
            name="payment_link_status",
            create_type=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        server_default=text("'issued'"),
        default=PaymentLinkStatus.ISSUED,
    )
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0"), default=Decimal("0")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
