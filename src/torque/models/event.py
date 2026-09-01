"""`Event` — Blueprint Section 3 / Section 2.5.

The raw inbound signal log. `idempotency_key` is sourced from Razorpay's
`X-Razorpay-Event-Id` header (unique per event including retries) — NEVER
derived from payload content — and is the dedup mechanism via its unique
constraint. The HTTP endpoint that verifies and writes these rows is Module 2;
Milestone 1 provides the table and the verification helper only
(`torque.security.razorpay_signature`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.models.mixins import TimestampMixin, uuid_pk


class Event(Base, TenantScoped, TimestampMixin):
    __tablename__ = "event"

    event_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )

    # e.g. "payment.failed", "checkout.abandoned", "subscription.charged.failed",
    # "invoice.overdue", "payment_link.paid", ...
    type: Mapped[str] = mapped_column(String(64), nullable=False)

    # = X-Razorpay-Event-Id. Unique constraint IS the idempotency mechanism.
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
