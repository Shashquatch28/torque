"""`Merchant_Counterparty` — Blueprint Section 3.

Join entity making relationship data merchant-scoped. Also carries the
incrementality cohort assignment (once per merchant-relationship, persists
across every leg) and the WhatsApp service-conversation window.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.exceptions import CohortAlreadyAssignedError
from torque.models.mixins import TimestampMixin, uuid_pk


class MerchantCounterparty(Base, TenantScoped, TimestampMixin):
    __tablename__ = "merchant_counterparty"
    __table_args__ = (UniqueConstraint("merchant_id", "counterparty_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparty.counterparty_id"), nullable=False, index=True
    )

    # Scoped to THIS merchant relationship only.
    payment_history_summary: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    promise_keeping_rate: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)

    # Incrementality randomisation unit. Assigned ONCE, then immutable — a
    # counterparty cannot be treatment on one case and control on another for
    # the same merchant. NULL means "not yet assigned".
    in_control_cohort: Mapped[bool | None] = mapped_column(Boolean)
    cohort_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # When the current 24h WhatsApp *service* conversation window closes.
    # While now() < this: Module 6 routes to a human agent, not templates.
    active_wa_conversation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    def assign_cohort(self, in_control: bool) -> None:
        """Set the cohort exactly once. Raises if already assigned."""
        if self.in_control_cohort is not None:
            raise CohortAlreadyAssignedError(
                f"cohort already assigned for merchant_counterparty {self.id}"
            )
        self.in_control_cohort = in_control
        self.cohort_assigned_at = datetime.now(UTC)
