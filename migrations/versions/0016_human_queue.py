"""0016 - human_queue (Module 6 §6.4 — Compliance & Cross-Leg Guardrail Engine)

The persistent human queue: a FIFO-per-merchant list keyed on `case_id`, fed by
three Module 6 feeders (low-confidence `ESCALATED_TO_HUMAN` sweep, escalation-
ceiling, broken `PromiseToPay`) plus the open-WhatsApp-conversation defer path.
Each row carries a `reason` (free string — vocabulary owned in
`torque.coordination.human_queue`, not a Postgres enum) and a `priority` (the
Module 8 economic-score seam; the placeholder is `amount_at_risk`).

`UNIQUE(case_id)` is the idempotency backstop — a case is queued at most once, so
a re-run of any feeder is a no-op.

Additive: one new table, no enum, no ALTER on any existing table, no new
`CaseEventType` (the closed §4 vocabulary is untouched).

Revision ID: 0016_human_queue
Revises: 0015_scheduled_job
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_human_queue"
down_revision: str | None = "0015_scheduled_job"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "human_queue",
        sa.Column(
            "entry_id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id", _UUID, sa.ForeignKey("revenue_leak_case.case_id"), nullable=False
        ),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("priority", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "enqueued_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("case_id", name="uq_human_queue_case_id"),
    )
    op.create_index("ix_human_queue_merchant_id", "human_queue", ["merchant_id"])
    op.create_index("ix_human_queue_enqueued_at", "human_queue", ["enqueued_at"])


def downgrade() -> None:
    op.drop_table("human_queue")
