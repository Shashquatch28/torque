"""0005 — the single audit/history mechanism: case_event (append-only)

Append-only is enforced at the database with a BEFORE UPDATE OR DELETE trigger
that raises, in addition to the application-layer `before_flush` guard. Blueprint
Section 2.3: CaseEvent replaces AuditLogEntry and PlaybookRun.step_history
entirely.

Revision ID: 0005_case_event
Revises: 0004_case_and_invoice
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_case_event"
down_revision: str | None = "0004_case_and_invoice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)

_IMMUTABLE_FN = """
CREATE OR REPLACE FUNCTION torque_case_event_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'case_event is append-only (Blueprint Section 2.3): % rejected', TG_OP;
END;
$$;
"""

_TRIGGER = """
CREATE TRIGGER case_event_no_mutate
BEFORE UPDATE OR DELETE ON case_event
FOR EACH ROW EXECUTE FUNCTION torque_case_event_immutable()
"""


def upgrade() -> None:
    op.create_table(
        "case_event",
        # PK, auto-incrementing, globally ordered (single sequence, all cases).
        sa.Column(
            "event_seq_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
        ),
        sa.Column(
            "case_id",
            _UUID,
            sa.ForeignKey("revenue_leak_case.case_id"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_id",
            _UUID,
            sa.ForeignKey("counterparty.counterparty_id"),
            nullable=True,
        ),
        sa.Column(
            "event_type",
            postgresql.ENUM(name="case_event_type", create_type=False),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column(
            "actor",
            postgresql.ENUM(name="actor", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_case_event_case_id", "case_event", ["case_id"])
    op.execute(_IMMUTABLE_FN)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS case_event_no_mutate ON case_event")
    op.execute("DROP FUNCTION IF EXISTS torque_case_event_immutable()")
    op.drop_table("case_event")
