"""0011 - payment_link, promise_to_pay (Milestone 6a - close the Core Data Model)

Blueprint Section 3. Schema + constraints only:
- payment_link : tenant-scoped; action_id NULLABLE (externally-originated links);
                 coherence (status = 'paid') <=> (paid_at IS NOT NULL).
- promise_to_pay : tenant-scoped; surrogate promise_id PK; captured_via UNIQUE
                   (0..1 PromiseToPay per Action). Status lifecycle enforced in
                   torque.promises + the before_flush guard - NOT here.

Reuses existing enum types payment_link_status / promise_status (created in
0001) - not recreated. No ALTER on any existing table. No seed.

MerchantWhatsAppTemplate is deliberately NOT in this migration (Milestone 6b).

Revision ID: 0011_payment_link_promise
Revises: 0010_actions
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_payment_link_promise"
down_revision: str | None = "0010_actions"
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
        "payment_link",
        sa.Column("link_id", sa.String(64), primary_key=True),
        sa.Column(
            "merchant_id",
            sa.String(64),
            sa.ForeignKey("merchant.merchant_id"),
            nullable=False,
        ),
        sa.Column(
            "action_id",
            _UUID,
            sa.ForeignKey("action.action_id"),
            nullable=True,
        ),
        sa.Column(
            "case_id",
            _UUID,
            sa.ForeignKey("revenue_leak_case.case_id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="payment_link_status", create_type=False),
            nullable=False,
            server_default=sa.text("'issued'"),
        ),
        sa.Column(
            "amount_paid",
            sa.Numeric(14, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("amount_paid >= 0", name="amount_paid_non_negative"),
        sa.CheckConstraint(
            "(status = 'paid') = (paid_at IS NOT NULL)",
            name="paid_status_matches_paid_at",
        ),
    )
    op.create_index("ix_payment_link_merchant_id", "payment_link", ["merchant_id"])
    op.create_index("ix_payment_link_action_id", "payment_link", ["action_id"])
    op.create_index("ix_payment_link_case_id", "payment_link", ["case_id"])

    op.create_table(
        "promise_to_pay",
        sa.Column(
            "promise_id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
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
        sa.Column(
            "captured_via",
            _UUID,
            sa.ForeignKey("action.action_id"),
            nullable=False,
        ),
        sa.Column("promised_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("promised_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="promise_status", create_type=False),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        *_timestamps(),
        sa.UniqueConstraint("captured_via", name="uq_promise_to_pay_captured_via"),
        sa.CheckConstraint(
            "promised_amount >= 0", name="promised_amount_non_negative"
        ),
    )
    op.create_index("ix_promise_to_pay_merchant_id", "promise_to_pay", ["merchant_id"])
    op.create_index("ix_promise_to_pay_case_id", "promise_to_pay", ["case_id"])


def downgrade() -> None:
    op.drop_table("promise_to_pay")
    op.drop_table("payment_link")
