"""0004 — case spine: revenue_leak_case, b2b_invoice

Revision ID: 0004_case_and_invoice
Revises: 0003_event
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_case_and_invoice"
down_revision: str | None = "0003_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "revenue_leak_case",
        sa.Column(
            "case_id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column(
            "leg_type",
            postgresql.ENUM(name="leg_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "source_event_id",
            _UUID,
            sa.ForeignKey("event.event_id"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_id",
            _UUID,
            sa.ForeignKey("counterparty.counterparty_id"),
            nullable=False,
        ),
        # Nullable FK -> SystemicEvent; the table lands in Milestone 2, so no
        # FK constraint yet — just the column, to keep the case shape stable.
        sa.Column("systemic_event_id", _UUID, nullable=True),
        sa.Column("amount_at_risk", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="case_status", create_type=False),
            nullable=False,
            server_default=sa.text("'DETECTED'"),
        ),
        sa.Column("root_cause_code", sa.String(64), nullable=True),
        sa.Column("root_cause_label", sa.String(256), nullable=True),
        sa.Column("network_directive_mac_code", sa.String(8), nullable=True),
        sa.Column(
            "network_directive_tier",
            postgresql.ENUM(name="mac_tier", create_type=False),
            nullable=True,
        ),
        sa.Column("diagnosis_confidence", sa.Float(), nullable=True),
        sa.Column(
            "context",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("control_group", sa.Boolean(), nullable=True),
        sa.Column(
            "superseded_by_case_id",
            _UUID,
            sa.ForeignKey("revenue_leak_case.case_id"),
            nullable=True,
        ),
        sa.Column(
            "recovery_type",
            postgresql.ENUM(name="recovery_type", create_type=False),
            nullable=True,
        ),
        sa.Column("recovered_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        # Bare names — the Base metadata naming convention renders these as
        # ck_revenue_leak_case_<name>, matching the model's __table_args__.
        sa.CheckConstraint(
            "diagnosis_confidence IS NULL OR "
            "(diagnosis_confidence >= 0 AND diagnosis_confidence <= 1)",
            name="diagnosis_confidence_unit_range",
        ),
        sa.CheckConstraint("amount_at_risk >= 0", name="amount_at_risk_non_negative"),
        sa.CheckConstraint(
            "recovered_amount IS NULL OR recovered_amount >= 0",
            name="recovered_amount_non_negative",
        ),
    )
    op.create_index("ix_revenue_leak_case_merchant_id", "revenue_leak_case", ["merchant_id"])
    op.create_index(
        "ix_revenue_leak_case_counterparty_id", "revenue_leak_case", ["counterparty_id"]
    )

    op.create_table(
        "b2b_invoice",
        sa.Column(
            "invoice_id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "case_id",
            _UUID,
            sa.ForeignKey("revenue_leak_case.case_id"),
            nullable=True,
        ),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column(
            "counterparty_id",
            _UUID,
            sa.ForeignKey("counterparty.counterparty_id"),
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("days_overdue", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("original_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("outstanding_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("gst_inclusive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payment_terms", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.CheckConstraint("original_amount >= 0", name="original_amount_non_negative"),
        sa.CheckConstraint(
            "outstanding_amount >= 0", name="outstanding_amount_non_negative"
        ),
        sa.CheckConstraint(
            "outstanding_amount <= original_amount",
            name="outstanding_not_above_original",
        ),
        sa.CheckConstraint("days_overdue >= 0", name="days_overdue_non_negative"),
    )
    op.create_index("ix_b2b_invoice_case_id", "b2b_invoice", ["case_id"])
    op.create_index("ix_b2b_invoice_merchant_id", "b2b_invoice", ["merchant_id"])
    op.create_index("ix_b2b_invoice_counterparty_id", "b2b_invoice", ["counterparty_id"])


def downgrade() -> None:
    op.drop_table("b2b_invoice")
    op.drop_table("revenue_leak_case")
