"""`Action` - one action Torque took (or was blocked from taking) on a case.

Blueprint Section 3 / Section 2.3. Tenant-scoped.

* `primary_case_id` is the lead case. Attribution ALWAYS lives in `ActionCase`
  rows (>= 1 per Action, Milestone 5 deviation 2) - there is no implicit
  "no rows => 100% primary_case_id" fallback.
* `run_id` is NULLABLE (Milestone 5): `NULL` = system-level or human-override
  activity not tied to a `PlaybookRun` (e.g. a `SYSTEMIC_HOLD` action taken
  before any run exists).
* Every `Action` write and its correlated `CaseEvent` write happen in ONE
  transaction (Section 2.3) - use `torque.events.write_action_and_event`; the
  `before_flush` guard structurally enforces it.
* `content_sent` references `counterparty_id` only, no embedded PII; it is the
  erasure-cascade target - a nullable column now, cascade orchestration
  deferred (Decision H).

Coherence constraints (DB CHECKs, same enum/detail-field pattern as
`card_retry_budget.hard_stop_reason_coherent`):
* `outcome = BLOCKED_BY_GUARDRAIL`  <=>  `block_reason IS NOT NULL`
* `outcome = BLOCKED_BY_GUARDRAIL`  <=>  `executed_at IS NULL`
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
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import ActionOutcome, ActionType, BlockReason
from torque.models.mixins import TimestampMixin, uuid_pk


class Action(Base, TenantScoped, TimestampMixin):
    __tablename__ = "action"
    __table_args__ = (
        CheckConstraint(
            "(outcome = 'BLOCKED_BY_GUARDRAIL') = (block_reason IS NOT NULL)",
            name="outcome_block_reason_coherent",
        ),
        CheckConstraint(
            "(outcome = 'BLOCKED_BY_GUARDRAIL') = (executed_at IS NULL)",
            name="executed_at_matches_outcome",
        ),
        CheckConstraint("cost IS NULL OR cost >= 0", name="cost_non_negative"),
    )

    action_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    primary_case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("playbook_run.run_id"), nullable=True, index=True
    )

    action_type: Mapped[ActionType] = mapped_column(
        PgEnum(ActionType, name="action_type", create_type=False), nullable=False
    )
    channel: Mapped[str | None] = mapped_column(String(32))
    content_sent: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[ActionOutcome] = mapped_column(
        PgEnum(ActionOutcome, name="action_outcome", create_type=False), nullable=False
    )
    block_reason: Mapped[BlockReason | None] = mapped_column(
        PgEnum(BlockReason, name="block_reason", create_type=False)
    )
    # Rs - plain nullable column; ChannelRateCard lookup / pricing is deferred.
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
