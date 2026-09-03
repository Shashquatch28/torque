"""0015 - scheduled_job (Postgres-polling execution driver — Module 5, §5.6)

The durable-timer row for the Postgres-polling `PlaybookRun` execution driver
chosen over Temporal for the build window (U-07 → D-090). One pending row per run
(`UNIQUE(run_id)`); a poller claims due rows with `FOR UPDATE SKIP LOCKED`,
executes the run's current step in one transaction, then advances `fire_at` or
deletes the row. No new enum (reuses `leg_type` from 0001).

Additive: one new table, no ALTER on any existing table.

Revision ID: 0015_scheduled_job
Revises: 0014_diagnosis_timing
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_scheduled_job"
down_revision: str | None = "0014_diagnosis_timing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "scheduled_job",
        sa.Column(
            "job_id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column(
            "run_id", _UUID, sa.ForeignKey("playbook_run.run_id"), nullable=False
        ),
        sa.Column(
            "case_id", _UUID, sa.ForeignKey("revenue_leak_case.case_id"), nullable=False
        ),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "leg_type",
            postgresql.ENUM(name="leg_type", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("run_id", name="uq_scheduled_job_run_id"),
    )
    op.create_index("ix_scheduled_job_merchant_id", "scheduled_job", ["merchant_id"])
    op.create_index("ix_scheduled_job_fire_at", "scheduled_job", ["fire_at"])


def downgrade() -> None:
    op.drop_table("scheduled_job")
