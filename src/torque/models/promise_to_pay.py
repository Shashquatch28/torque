"""`PromiseToPay` - a promise-to-pay captured on a case. Blueprint Section 3.

* `captured_via` is the `Action` that captured the promise. `UNIQUE(captured_via)`
  enforces the diagram's 0..1-PromiseToPay-per-Action relationship at the DB.
* `status` lifecycle: `PENDING -> KEPT` or `PENDING -> BROKEN`; `KEPT` / `BROKEN`
  are terminal. Enforced by `torque.promises` (helper) AND the `before_flush`
  guard in `torque.models.guards` - both agree on exactly that graph.
* No `CaseEvent` is written on a status change (`PROMISE_CAPTURED` is the
  capture-time event, a Module 5 execution concern).
* **No `on_broken` column** (decision D4): a `BROKEN` promise routes to the human
  queue - that is Module 6 runtime behaviour, not per-row configuration.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import PromiseStatus
from torque.models.mixins import TimestampMixin, uuid_pk


class PromiseToPay(Base, TenantScoped, TimestampMixin):
    __tablename__ = "promise_to_pay"
    __table_args__ = (
        UniqueConstraint("captured_via", name="uq_promise_to_pay_captured_via"),
        CheckConstraint("promised_amount >= 0", name="promised_amount_non_negative"),
    )

    promise_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=False, index=True
    )
    # The Action that captured this promise (typically a LOG_PROMISE action).
    captured_via: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("action.action_id"), nullable=False
    )

    promised_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    promised_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PromiseStatus] = mapped_column(
        PgEnum(PromiseStatus, name="promise_status", create_type=False),
        nullable=False,
        server_default=text("'PENDING'"),
        default=PromiseStatus.PENDING,
    )
