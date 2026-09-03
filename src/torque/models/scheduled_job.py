"""`ScheduledJob` — the Postgres-polling execution driver's timer row.

Blueprint §5.6 (the fallback chosen over Temporal for the build window — U-07
resolved to Postgres-polling, D-090). One pending job per `PlaybookRun`: it says
"at `fire_at`, execute this run's current `active_step_id`." A poller claims due
rows with `SELECT … FOR UPDATE SKIP LOCKED`, executes the step in one transaction,
then either advances `fire_at` to the next step's computed fire time (run
continues) or deletes the row (run reached a terminal outcome).

`UNIQUE(run_id)` enforces the "at most one pending timer per run" invariant — the
structural basis for idempotent scheduling and exactly-once step execution:
claim-under-lock + the single-transaction step write mean a duplicate poll finds
no row to claim, and a crashed transaction leaves the row untouched for the next
poll (at-least-once delivery, exactly-once effect).

`leg_type` is denormalised from the case so the two stratified pollers (§5.6: a
10 s loop for `PAYMENT_DEGRADATION`'s live-session window, a 60 s loop for the
other three legs) can filter without a join in the hot path. Tenant-scoped.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import LegType
from torque.models.mixins import TimestampMixin, uuid_pk


class ScheduledJob(Base, TenantScoped, TimestampMixin):
    __tablename__ = "scheduled_job"
    __table_args__ = (UniqueConstraint("run_id", name="uq_scheduled_job_run_id"),)

    job_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("playbook_run.run_id"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=False
    )
    # When this run's current step becomes eligible to fire (UTC).
    fire_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # Denormalised from the case — drives the 10 s / 60 s poller stratification.
    leg_type: Mapped[LegType] = mapped_column(
        PgEnum(LegType, name="leg_type", create_type=False), nullable=False
    )
