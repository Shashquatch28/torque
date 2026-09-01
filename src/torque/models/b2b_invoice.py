"""`B2BInvoice` — Blueprint Section 3.

One case can bundle multiple overdue invoices for the same counterparty into a
single dunning thread. `case_id` is nullable until the invoice is triaged;
multiple invoices can share one `case_id`. The bundling *trigger* (on
`invoice.overdue`, look for an open non-terminal B2B case for the same
merchant+counterparty) runs in Module 2 — this milestone provides the table and
its partial-payment arithmetic constraints only.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.models.mixins import TimestampMixin, uuid_pk


class B2BInvoice(Base, TenantScoped, TimestampMixin):
    __tablename__ = "b2b_invoice"
    __table_args__ = (
        CheckConstraint("original_amount >= 0", name="original_amount_non_negative"),
        CheckConstraint("outstanding_amount >= 0", name="outstanding_amount_non_negative"),
        CheckConstraint(
            "outstanding_amount <= original_amount",
            name="outstanding_not_above_original",
        ),
        CheckConstraint("days_overdue >= 0", name="days_overdue_non_negative"),
    )

    invoice_id: Mapped[uuid.UUID] = uuid_pk()
    # Nullable until triaged; many invoices -> one case.
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=True, index=True
    )
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparty.counterparty_id"), nullable=False, index=True
    )

    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_overdue: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    original_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # A partial payment decrements this; the case stays PARTIALLY_RECOVERED.
    outstanding_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    gst_inclusive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_terms: Mapped[str | None] = mapped_column(String(64))
