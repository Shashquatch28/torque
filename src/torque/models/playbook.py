"""`Playbook` - a single immutable, versioned playbook definition.

Blueprint Section 3 / Section 2.4. Global (product-owned) - **no `merchant_id`**;
per-merchant tuning lives in `MerchantPlaybookConfig`.

**Strict append-only (decision B / 3):** a `(playbook_id, version)` row is never
UPDATEd or DELETEd. Every edit inserts `version + 1`. There is no mutable
"latest" row. Enforced two ways:
* a Postgres `BEFORE UPDATE OR DELETE` trigger (`playbook_no_mutate`, migration
  0009) that raises;
* the `before_flush` guard (`torque.models.guards`) rejecting dirty/deleted
  `Playbook` instances.
Mirrors the immutability model of `CaseEvent`. No `updated_at` column.

`steps_graph` and `stopping_rules` are validated against the typed models in
`torque.playbooks` at flush time by the same guard.

`step_timing_semantics` is deliberately NOT a column (decision K): it is a fixed
system-wide interpretation rule - each `timing_offset_hours` is measured from the
previous step's actual completion timestamp, and a fire-time outside
`stopping_rules.allowed_hours` defers to the next allowed window (never fires
early, never silently skips). Module 5 implements it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base
from torque.enums import LegType, MandateType


class Playbook(Base):
    __tablename__ = "playbook"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
    )

    playbook_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("playbook_identity.playbook_id"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)

    leg_type: Mapped[LegType] = mapped_column(
        PgEnum(LegType, name="leg_type", create_type=False), nullable=False
    )
    # Nullable discriminator (decision C). Set only for leg-3 playbooks; drives
    # the UPI AutoPay max_attempts <= 3 save-time rule. Directly queryable.
    mandate_type: Mapped[MandateType | None] = mapped_column(
        PgEnum(MandateType, name="mandate_type", create_type=False)
    )

    # Freeform (decision H) - structure belongs to later diagnosis/runtime.
    trigger_condition: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # Validated against torque.playbooks.StepGraph at flush (guard).
    steps_graph: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Template defaults; validated against torque.playbooks.StoppingRules at
    # flush (guard). Merchant overrides merge onto this.
    stopping_rules: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Append-only: created_at only, NO updated_at.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
