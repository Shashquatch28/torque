"""`ActionCase` - per-case attribution for an `Action`. Blueprint Section 3 / Section 5.

Replaces the eliminated `Action.merged_case_ids` array. Tenant-scoped.

**Every `Action` has one or more `ActionCase` rows** (Milestone 5 deviation 2 -
the blueprint frames `ActionCase` as multi-case-only; Torque makes attribution
universal so every downstream consumer, especially Module 7, uses one query:
`SELECT case_id, credit_weight FROM action_case WHERE action_id = :id`).

Invariants (guard-enforced in `torque.models.guards` - Postgres cannot express a
cross-row sum in a CHECK):
* exactly one row per `action_id` has `is_primary = true`;
* that row's `case_id` equals the parent `Action.primary_case_id`;
* Σ `credit_weight` over an `action_id` == `Decimal("1.00000")` (exact Decimal
  arithmetic - never float);
* the complete set is present in the same flush that creates the `Action`
  (same-flush completeness).

`credit_weight` is mutable: Module 7 re-splits it proportionally at
reconciliation; every update re-runs the full validation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.models.mixins import TimestampMixin


class ActionCase(Base, TenantScoped, TimestampMixin):
    __tablename__ = "action_case"
    __table_args__ = (
        CheckConstraint(
            "credit_weight >= 0 AND credit_weight <= 1", name="credit_weight_unit_range"
        ),
    )

    action_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("action.action_id"), primary_key=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), primary_key=True, index=True
    )
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    credit_weight: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
