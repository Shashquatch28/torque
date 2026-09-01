"""0010 - action, action_case (the atomic, always-attributed action ledger)

Blueprint Section 3 / Section 2.3 / Section 5. Schema + the atomic-write
primitive + guard enforcement (in code). No channel adapters, no execution, no
reconciliation, no cost lookup.

- action      : tenant-scoped; run_id NULLABLE (system / human-override activity);
                outcome NOT NULL; coherence CHECKs outcome<->block_reason and
                outcome<->executed_at; cost non-negative.
- action_case : tenant-scoped; composite PK (action_id, case_id);
                credit_weight Numeric(6,5). Sum-to-1.00000 / exactly-one-primary
                / primary-matches-Action.primary_case_id / same-flush
                completeness are guard-enforced (Postgres cannot express a
                cross-row sum in a CHECK).

No new enum types (action_type / action_outcome / block_reason created in 0001).
No ALTER on any existing table.

Revision ID: 0010_actions
Revises: 0009_playbooks
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_actions"
down_revision: str | None = "0009_playbooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_UUID = postgresql.UUID(as_uuid=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    ]


def upgrade() -> None:
    op.create_table(
        "action",
        sa.Column(
            "action_id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column(
            "primary_case_id",
            _UUID,
            sa.ForeignKey("revenue_leak_case.case_id"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            _UUID,
            sa.ForeignKey("playbook_run.run_id"),
            nullable=True,
        ),
        sa.Column(
            "action_type",
            postgresql.ENUM(name="action_type", create_type=False),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=True),
        sa.Column("content_sent", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outcome",
            postgresql.ENUM(name="action_outcome", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "block_reason",
            postgresql.ENUM(name="block_reason", create_type=False),
            nullable=True,
        ),
        sa.Column("cost", sa.Numeric(14, 4), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "(outcome = 'BLOCKED_BY_GUARDRAIL') = (block_reason IS NOT NULL)",
            name="outcome_block_reason_coherent",
        ),
        sa.CheckConstraint(
            "(outcome = 'BLOCKED_BY_GUARDRAIL') = (executed_at IS NULL)",
            name="executed_at_matches_outcome",
        ),
        sa.CheckConstraint("cost IS NULL OR cost >= 0", name="cost_non_negative"),
    )
    op.create_index("ix_action_merchant_id", "action", ["merchant_id"])
    op.create_index("ix_action_primary_case_id", "action", ["primary_case_id"])
    op.create_index("ix_action_run_id", "action", ["run_id"])

    op.create_table(
        "action_case",
        sa.Column(
            "action_id",
            _UUID,
            sa.ForeignKey("action.action_id"),
            primary_key=True,
        ),
        sa.Column(
            "case_id",
            _UUID,
            sa.ForeignKey("revenue_leak_case.case_id"),
            primary_key=True,
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("credit_weight", sa.Numeric(6, 5), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "credit_weight >= 0 AND credit_weight <= 1", name="credit_weight_unit_range"
        ),
    )
    op.create_index("ix_action_case_case_id", "action_case", ["case_id"])
    op.create_index("ix_action_case_merchant_id", "action_case", ["merchant_id"])


def downgrade() -> None:
    op.drop_table("action_case")
    op.drop_table("action")
