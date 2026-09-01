"""0012 - merchant_whatsapp_template (Milestone 6b - close Section 3)

Blueprint Section 3, WhatsApp gate #2 of 2. Schema + one enum only; the
`approved_template_exists` predicate and all enforcement live in code / Module 6.

- Creates the `whatsapp_template_category` Postgres enum (UTILITY, MARKETING).
  `AUTHENTICATION` is deliberately NOT included - add it later with an explicit
  `ALTER TYPE ... ADD VALUE` migration if Torque ever needs OTP/auth templates.
- `approval_status` is a plain `String(32)` - NO Postgres enum, NO CHECK. Meta
  owns and evolves that vocabulary; the compliance invariant is exact
  `approval_status = 'APPROVED'`, everything else fails closed, and future Meta
  statuses persist without a schema migration.
- Reuses the existing `leg_type` Postgres enum (created in 0001).
- No ALTER on existing tables. No seed.

Revision ID: 0012_merchant_whatsapp_template
Revises: 0011_payment_link_promise
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_merchant_whatsapp_template"
down_revision: str | None = "0011_payment_link_promise"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")

_CATEGORY = postgresql.ENUM(
    "UTILITY", "MARKETING", name="whatsapp_template_category"
)


def upgrade() -> None:
    _CATEGORY.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "merchant_whatsapp_template",
        sa.Column("template_id", sa.String(128), primary_key=True),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column("template_name", sa.String(256), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(name="whatsapp_template_category", create_type=False),
            nullable=False,
        ),
        # Meta-owned free string - no enum, no CHECK.
        sa.Column("approval_status", sa.String(32), nullable=False),
        sa.Column(
            "leg_type",
            postgresql.ENUM(name="leg_type", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index(
        "ix_merchant_whatsapp_template_merchant_id",
        "merchant_whatsapp_template",
        ["merchant_id"],
    )
    op.create_index(
        "ix_merchant_whatsapp_template_gate",
        "merchant_whatsapp_template",
        ["merchant_id", "leg_type", "category"],
    )


def downgrade() -> None:
    op.drop_table("merchant_whatsapp_template")
    _CATEGORY.drop(op.get_bind(), checkfirst=True)
