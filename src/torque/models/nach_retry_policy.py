"""`NACHRetryPolicy` — NACH / e-NACH representment posture. Blueprint Section 3.

NACH has **no NPCI-standardised fixed attempt cap** — a structurally different
compliance posture from card and UPI. Individual banks track dishonour frequency
per financial year (commonly a 3-5 threshold) at the account level. Torque's
ceiling is **self-imposed**, merchant-configurable, recommended default 3
representments per billing cycle — that default lives in
`PolicyConfig.nach_representment_ceiling_default` and will be copied into
`Playbook.stopping_rules.max_attempts` by Module 4.

`torque.compliance.retry_rails.nach_retry_eligible` is the pure predicate;
enforcement is Module 5. Cross-instrument (cheque + NACH) aggregation is
roadmap (Part E item 4) and is NOT modelled here.

`merchant_id` + tenant scoping added (decision 1); `mandate_id` is an indexed
external identifier, not a DB foreign key (decision 2).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import ClearingCycleStatus
from torque.models.mixins import TimestampMixin, uuid_pk


class NACHRetryPolicy(Base, TenantScoped, TimestampMixin):
    __tablename__ = "nach_retry_policy"
    __table_args__ = (
        UniqueConstraint("mandate_id", "merchant_id"),
        CheckConstraint(
            "dishonour_count_this_fy >= 0", name="dishonour_count_non_negative"
        ),
    )

    nach_retry_policy_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    mandate_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # NACH returns take 3-7 banking days, batch clearing, not real-time.
    clearing_cycle_status: Mapped[ClearingCycleStatus] = mapped_column(
        PgEnum(ClearingCycleStatus, name="clearing_cycle_status", create_type=False),
        nullable=False,
    )
    return_reason_code: Mapped[str | None] = mapped_column(String(16))
    # Date of the next batch clearing window.
    retry_eligible_after: Mapped[date | None] = mapped_column(Date)
    # Running counter per mandate — a conservative proxy (no visibility into
    # other instruments at the same bank).
    dishonour_count_this_fy: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
