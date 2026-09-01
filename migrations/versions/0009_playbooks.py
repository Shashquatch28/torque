"""0009 - playbook_identity, playbook (append-only), merchant_playbook_config, playbook_run

Blueprint Section 3 / Section 4 / Section 2.4. Schema + validation contract only:
no catalog seed, no selection, no runtime traversal.

- playbook_identity : global identity anchor (playbook_id slug PK)
- playbook          : global, versioned, STRICT append-only (composite PK
                      (playbook_id, version); BEFORE UPDATE OR DELETE trigger)
- merchant_playbook_config : tenant-scoped stopping-rules override + enabled flag
- playbook_run      : tenant-scoped, version-pinned via composite FK

No new enum types (leg_type, mandate_type, playbook_run_status created in 0001).
No ALTER on any existing table.

Revision ID: 0009_playbooks
Revises: 0008_systemic_and_rate_card
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_playbooks"
down_revision: str | None = "0008_systemic_and_rate_card"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_UUID = postgresql.UUID(as_uuid=True)

_IMMUTABLE_FN = """
CREATE OR REPLACE FUNCTION torque_playbook_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'playbook versions are append-only (Blueprint Section 2.4): % rejected', TG_OP;
END;
$$;
"""

_TRIGGER = """
CREATE TRIGGER playbook_no_mutate
BEFORE UPDATE OR DELETE ON playbook
FOR EACH ROW EXECUTE FUNCTION torque_playbook_immutable()
"""


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    ]


def upgrade() -> None:
    # --- playbook_identity -------------------------------------------------
    op.create_table(
        "playbook_identity",
        sa.Column("playbook_id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )

    # --- playbook (append-only, versioned) ---------------------------
    op.create_table(
        "playbook",
        sa.Column(
            "playbook_id",
            sa.String(64),
            sa.ForeignKey("playbook_identity.playbook_id"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column(
            "leg_type",
            postgresql.ENUM(name="leg_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "mandate_type",
            postgresql.ENUM(name="mandate_type", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "trigger_condition",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("steps_graph", postgresql.JSONB(), nullable=False),
        sa.Column("stopping_rules", postgresql.JSONB(), nullable=False),
        # Append-only: created_at only, NO updated_at.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index("ix_playbook_playbook_id", "playbook", ["playbook_id"])
    op.create_index("ix_playbook_leg_type", "playbook", ["leg_type"])
    op.execute(_IMMUTABLE_FN)
    op.execute(_TRIGGER)

    # --- merchant_playbook_config (tenant-scoped, mutable) ---------
    op.create_table(
        "merchant_playbook_config",
        sa.Column(
            "id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column(
            "playbook_id",
            sa.String(64),
            sa.ForeignKey("playbook_identity.playbook_id"),
            nullable=False,
        ),
        sa.Column("stopping_rules_override", postgresql.JSONB(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint(
            "merchant_id", "playbook_id", name="uq_merchant_playbook_config_merchant_id"
        ),
    )
    op.create_index(
        "ix_merchant_playbook_config_merchant_id",
        "merchant_playbook_config",
        ["merchant_id"],
    )

    # --- playbook_run (tenant-scoped, version-pinned) --------------
    op.create_table(
        "playbook_run",
        sa.Column(
            "run_id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            _UUID,
            sa.ForeignKey("revenue_leak_case.case_id"),
            nullable=False,
        ),
        sa.Column("playbook_id", sa.String(64), nullable=False),
        sa.Column("playbook_version", sa.Integer(), nullable=False),
        sa.Column("active_step_id", sa.String(64), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="playbook_run_status", create_type=False),
            nullable=False,
            server_default=sa.text("'RUNNING'"),
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["playbook_id", "playbook_version"],
            ["playbook.playbook_id", "playbook.version"],
            name="fk_playbook_run_playbook_id_playbook",
        ),
    )
    op.create_index("ix_playbook_run_case_id", "playbook_run", ["case_id"])
    op.create_index("ix_playbook_run_merchant_id", "playbook_run", ["merchant_id"])


def downgrade() -> None:
    op.drop_table("playbook_run")
    op.drop_table("merchant_playbook_config")
    op.execute("DROP TRIGGER IF EXISTS playbook_no_mutate ON playbook")
    op.execute("DROP FUNCTION IF EXISTS torque_playbook_immutable()")
    op.drop_table("playbook")
    op.drop_table("playbook_identity")
