"""0007 - retry-rail + pre-debit compliance tables

card_retry_budget, upi_retry_budget, nach_retry_policy, pre_debit_notification.
All new tables; no existing table is altered. No new enum types (network,
mac_tier, hard_stop_reason, clearing_cycle_status were all created in 0001).

Confirmed decisions: merchant_id + tenant scoping on all four; mandate_id is an
indexed String (no FK); upi_retry_budget has NO permitted_execution_window
column; hard_cap is a column with server_default 3 and CHECK (hard_cap = 3).

Revision ID: 0007_retry_budgets
Revises: 0006_mac_code_registry
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_retry_budgets"
down_revision: str | None = "0006_mac_code_registry"
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
    # --- card_retry_budget ------------------------------------------------
    op.create_table(
        "card_retry_budget",
        sa.Column(
            "budget_id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("card_token_hash", sa.String(128), nullable=False),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column("attempts_used_24h", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("attempts_used_30d", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("hard_stop", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "hard_stop_reason",
            postgresql.ENUM(name="hard_stop_reason", create_type=False),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "card_token_hash", "merchant_id", name="uq_card_retry_budget_card_token_hash"
        ),
        sa.CheckConstraint(
            "attempts_used_24h >= 0",
            name="attempts_used_24h_non_negative",
        ),
        sa.CheckConstraint(
            "attempts_used_30d >= 0",
            name="attempts_used_30d_non_negative",
        ),
        sa.CheckConstraint(
            "(hard_stop = false AND hard_stop_reason IS NULL) OR "
            "(hard_stop = true AND hard_stop_reason IS NOT NULL)",
            name="hard_stop_reason_coherent",
        ),
    )
    op.create_index("ix_card_retry_budget_merchant_id", "card_retry_budget", ["merchant_id"])

    # --- upi_retry_budget ----------------------------------------------
    op.create_table(
        "upi_retry_budget",
        sa.Column(
            "budget_id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column("mandate_id", sa.String(128), nullable=False),
        sa.Column("attempts_used", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("hard_cap", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("mandate_cancelled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "mandate_id", "merchant_id", name="uq_upi_retry_budget_mandate_id"
        ),
        sa.CheckConstraint(
            "attempts_used >= 0", name="upi_attempts_used_non_negative"
        ),
        sa.CheckConstraint("hard_cap = 3", name="upi_hard_cap_locked"),
    )
    op.create_index("ix_upi_retry_budget_merchant_id", "upi_retry_budget", ["merchant_id"])
    op.create_index("ix_upi_retry_budget_mandate_id", "upi_retry_budget", ["mandate_id"])

    # --- nach_retry_policy --------------------------------------------
    op.create_table(
        "nach_retry_policy",
        sa.Column(
            "nach_retry_policy_id",
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
        sa.Column("mandate_id", sa.String(128), nullable=False),
        sa.Column(
            "clearing_cycle_status",
            postgresql.ENUM(name="clearing_cycle_status", create_type=False),
            nullable=False,
        ),
        sa.Column("return_reason_code", sa.String(16), nullable=True),
        sa.Column("retry_eligible_after", sa.Date(), nullable=True),
        sa.Column(
            "dishonour_count_this_fy",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "mandate_id", "merchant_id", name="uq_nach_retry_policy_mandate_id"
        ),
        sa.CheckConstraint(
            "dishonour_count_this_fy >= 0",
            name="dishonour_count_non_negative",
        ),
    )
    op.create_index("ix_nach_retry_policy_merchant_id", "nach_retry_policy", ["merchant_id"])
    op.create_index("ix_nach_retry_policy_mandate_id", "nach_retry_policy", ["mandate_id"])

    # --- pre_debit_notification --------------------------------------
    op.create_table(
        "pre_debit_notification",
        sa.Column(
            "notification_id",
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
        sa.Column(
            "case_id",
            _UUID,
            sa.ForeignKey("revenue_leak_case.case_id"),
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("covers_attempt_number", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("notified_amount", sa.Numeric(14, 2), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "covers_attempt_number >= 1",
            name="covers_attempt_number_min",
        ),
        sa.CheckConstraint(
            "notified_amount >= 0",
            name="notified_amount_non_negative",
        ),
    )
    op.create_index(
        "ix_pre_debit_notification_merchant_id", "pre_debit_notification", ["merchant_id"]
    )
    op.create_index(
        "ix_pre_debit_notification_case_id", "pre_debit_notification", ["case_id"]
    )


def downgrade() -> None:
    op.drop_table("pre_debit_notification")
    op.drop_table("nach_retry_policy")
    op.drop_table("upi_retry_budget")
    op.drop_table("card_retry_budget")
