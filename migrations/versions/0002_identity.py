"""0002 — identity & consent: merchant, counterparty, merchant_counterparty

Revision ID: 0002_identity
Revises: 0001_enums
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_identity"
down_revision: str | None = "0001_enums"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("gen_random_uuid()")
_NOW = sa.text("now()")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    ]


def upgrade() -> None:
    op.create_table(
        "merchant",
        sa.Column("merchant_id", sa.String(64), primary_key=True),
        sa.Column("business_type", sa.String(64), nullable=True),
        sa.Column("tier", sa.String(32), nullable=True),
        sa.Column(
            "channels_enabled",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "risk_appetite_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_timestamps(),
    )

    op.create_table(
        "counterparty",
        sa.Column(
            "counterparty_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_DEFAULT,
        ),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column(
            "whatsapp_opt_in",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "payment_failure_nudge_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "language_pref",
            postgresql.ENUM(name="language_pref", create_type=False),
            nullable=False,
            server_default=sa.text("'HINGLISH'"),
        ),
        sa.Column(
            "consent_log",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        *_timestamps(),
    )

    op.create_table(
        "merchant_counterparty",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_DEFAULT,
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("counterparty.counterparty_id"),
            nullable=False,
        ),
        sa.Column(
            "payment_history_summary",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("promise_keeping_rate", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("in_control_cohort", sa.Boolean(), nullable=True),
        sa.Column("cohort_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "active_wa_conversation_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "merchant_id", "counterparty_id", name="uq_merchant_counterparty_merchant_id"
        ),
    )
    op.create_index(
        "ix_merchant_counterparty_merchant_id", "merchant_counterparty", ["merchant_id"]
    )
    op.create_index(
        "ix_merchant_counterparty_counterparty_id",
        "merchant_counterparty",
        ["counterparty_id"],
    )


def downgrade() -> None:
    op.drop_table("merchant_counterparty")
    op.drop_table("counterparty")
    op.drop_table("merchant")
