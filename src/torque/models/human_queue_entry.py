"""`HumanQueueEntry` — the Module 6 §6.4 human queue.

Blueprint §6.4: "a simple FIFO-per-merchant queue keyed on `case_id`, populated
from three independent sources that all land in the same place: low-confidence
diagnoses (Module 3 §3.3), escalation-ceiling cases (§6.3), and
`PromiseToPay.on_broken`. Each entry carries a `reason` and a `priority`."

Design (D-097 / Q-E):

* **Tenant-scoped** — every read/write goes through `TenantScope`.
* **Keyed on `case_id`** — a case is in the queue at most once. `UNIQUE(case_id)`
  is the idempotency backstop for repeated enqueue attempts (a re-run of any
  feeder is a no-op).
* **`reason`** is a plain `String(32)` — the vocabulary
  (`torque.coordination.human_queue.HumanQueueReason`) lives in the coordination
  layer, not the model, and is not a Postgres enum (same "keep the schema
  minimal, own the vocabulary in code" posture as
  `MerchantWhatsAppTemplate.approval_status`, D-042).
* **`priority`** — the economic score the queue is ordered by. Until Module 8
  exists this is the `amount_at_risk` placeholder from
  `torque.coordination.outreach_coordinator.priority()` (D-098 / Q-B); the real
  `(probability × amount_at_risk) ÷ cost` replaces it through that seam with no
  schema change (`Numeric(14, 2)` already matches `RevenueLeakCase.amount_at_risk`).
* **`enqueued_at`** — the FIFO ordering key (indexed).

Module 10 concerns (an agent claiming / resolving an entry, `escalation_resolution`,
`HUMAN_RESOLVED`) are deliberately **not** modelled here (Q-I).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.models.mixins import TimestampMixin, uuid_pk


class HumanQueueEntry(Base, TenantScoped, TimestampMixin):
    __tablename__ = "human_queue"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_human_queue_case_id"),
    )

    entry_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=False
    )

    # Why the case needs a human. Free string; vocabulary owned in the
    # coordination layer (HumanQueueReason).
    reason: Mapped[str] = mapped_column(String(32), nullable=False)

    # The economic score the queue is ordered by (Module 8 seam — placeholder is
    # amount_at_risk). Same precision as RevenueLeakCase.amount_at_risk.
    priority: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # FIFO ordering key.
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
