"""0008 - systemic_event, channel_rate_card, + revenue_leak_case FK wire-up

Completes the Phase-1 foundation configuration tables:
- systemic_event (tenant-scoped; ISSUER_SPECIFIC coherence CHECK)
- channel_rate_card (global; freeform String PK; seed whatsapp/email/sms only)
- adds the real FK on the existing revenue_leak_case.systemic_event_id column
  (default RESTRICT delete - a referenced SystemicEvent cannot be deleted).

No new enum types (network, systemic_scope created in 0001). No status
transitions, no detection job.

Revision ID: 0008_systemic_and_rate_card
Revises: 0007_retry_budgets
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_systemic_and_rate_card"
down_revision: str | None = "0007_retry_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_UUID = postgresql.UUID(as_uuid=True)

_FK_NAME = "fk_revenue_leak_case_systemic_event_id_systemic_event"
_IX_NAME = "ix_revenue_leak_case_systemic_event_id"


def upgrade() -> None:
    # --- systemic_event -------------------------------------------------
    op.create_table(
        "systemic_event",
        sa.Column(
            "systemic_event_id",
            _UUID,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column("issuer_code", sa.String(32), nullable=True),
        sa.Column(
            "network",
            postgresql.ENUM(name="network", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "scope",
            postgresql.ENUM(name="systemic_scope", create_type=False),
            nullable=False,
        ),
        sa.Column("failure_rate_at_detection", sa.Numeric(12, 4), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "affected_case_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint(
            "failure_rate_at_detection >= 0", name="failure_rate_non_negative"
        ),
        sa.CheckConstraint(
            "affected_case_count >= 0", name="affected_case_count_non_negative"
        ),
        sa.CheckConstraint(
            "scope = 'NETWORK_WIDE' OR issuer_code IS NOT NULL OR network IS NOT NULL",
            name="issuer_specific_names_a_target",
        ),
    )
    op.create_index("ix_systemic_event_merchant_id", "systemic_event", ["merchant_id"])

    # --- channel_rate_card -------------------------------------------
    op.create_table(
        "channel_rate_card",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("rate_per_unit", sa.Numeric(14, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint("rate_per_unit >= 0", name="rate_per_unit_non_negative"),
    )
    # Demo placeholder rates (Rs/unit) - realistic ballparks, actual demo spend $0.
    op.execute(
        "INSERT INTO channel_rate_card (channel, rate_per_unit) VALUES "
        "('whatsapp', 0.8850), ('email', 0.0100), ('sms', 0.2000)"
    )

    # --- wire the deferred FK on revenue_leak_case.systemic_event_id ----
    op.create_foreign_key(
        _FK_NAME,
        "revenue_leak_case",
        "systemic_event",
        ["systemic_event_id"],
        ["systemic_event_id"],
    )
    op.create_index(_IX_NAME, "revenue_leak_case", ["systemic_event_id"])


def downgrade() -> None:
    op.drop_index(_IX_NAME, table_name="revenue_leak_case")
    op.drop_constraint(_FK_NAME, "revenue_leak_case", type_="foreignkey")
    op.drop_table("channel_rate_card")
    op.drop_table("systemic_event")
