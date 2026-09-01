"""`PreDebitNotification` — per-attempt pre-debit tracking. Blueprint Section 3.

RBI Digital Payments - E-Mandate Framework, 2026: a pre-debit notification must
precede **each** debit/retry by >= 24h. This is a per-attempt table (it replaced
the earlier single `pre_debit_notified_at` field entirely).

Only ever represents **Torque-initiated retry notifications** — not the original
merchant/PSP failure notice.

The guardrail predicate (Module 6) is
`torque.compliance.pre_debit.gap_satisfied`:
    EXISTS(SELECT 1 FROM pre_debit_notification
           WHERE case_id = X AND covers_attempt_number = next_attempt
           AND now() - notified_at >= 24h)

`merchant_id` + tenant scoping added (decision 1); `case_id` is a real FK.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.models.mixins import TimestampMixin, uuid_pk


class PreDebitNotification(Base, TenantScoped, TimestampMixin):
    __tablename__ = "pre_debit_notification"
    __table_args__ = (
        CheckConstraint(
            "covers_attempt_number >= 1", name="covers_attempt_number_min"
        ),
        CheckConstraint("notified_amount >= 0", name="notified_amount_non_negative"),
    )

    notification_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=False, index=True
    )
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Which retry attempt this notification authorises (retries are 1-indexed).
    covers_attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    # The Rs amount actually communicated — can legitimately differ from the
    # original mandate amount (proration, partial-recovery scenarios).
    notified_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
