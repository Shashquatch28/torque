"""`UPIRetryBudget` — NPCI UPI AutoPay rules. Blueprint Section 3.

Two INDEPENDENT gates, both required (enforcement is Module 5):
1. attempt-count gate — `attempts_used < 3 AND mandate_cancelled_at IS NULL`
   (`torque.compliance.retry_rails.upi_attempt_gate_open`);
2. execution-window gate — the moment must be OUTSIDE NPCI's peak windows
   (`torque.compliance.retry_rails.within_upi_execution_window`).

Confirmed architectural decisions for this milestone:
* `merchant_id` + tenant scoping added (decision 1).
* `mandate_id` is an indexed external identifier `String`, NOT a DB foreign key —
  Torque has no internal `Mandate` entity (decision 2).
* `permitted_execution_window` is NOT a column — it is a module-level compliance
  constant plus a pure predicate (decision 3).
* `hard_cap` is a column with `server_default=3` and a `CHECK (hard_cap = 3)` —
  NPCI-enforced, not merchant-configurable (decision 4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.models.mixins import TimestampMixin, uuid_pk


class UPIRetryBudget(Base, TenantScoped, TimestampMixin):
    __tablename__ = "upi_retry_budget"
    __table_args__ = (
        UniqueConstraint("mandate_id", "merchant_id"),
        CheckConstraint("attempts_used >= 0", name="upi_attempts_used_non_negative"),
        CheckConstraint("hard_cap = 3", name="upi_hard_cap_locked"),
    )

    budget_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    # External NPCI mandate identifier — indexed, not a FK (no Mandate entity).
    mandate_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Includes the original attempt.
    attempts_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Constant 3 (1 original + 3 retries). Locked by the check constraint.
    hard_cap: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3"), default=3
    )
    # Set by Module 2 when NPCI confirms cancellation post-4th attempt.
    mandate_cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
