"""0013 - event ingestion lookup index (Milestone 7a - Module 2 begins)

Additive, non-breaking. No table, no column, no enum.

Adds one composite index on `event (merchant_id, type, received_at)`. Module 2's
cross-leg dedup (§2.4) and systemic detection job (§2.5) both read a merchant's
events of one `type` inside a trailing time window; the existing single-column
`ix_event_merchant_id` (from 0003) is only a prefix of that access pattern.

The M7a webhook endpoint itself does not need this index (it dedups on the
UNIQUE `idempotency_key`); it is added now because the need is named explicitly
in the blueprint rather than speculative, and splitting a second index migration
onto the same table later would be pure churn.

Revision ID: 0013_event_ingestion_index
Revises: 0012_merchant_whatsapp_template
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_event_ingestion_index"
down_revision: str | None = "0012_merchant_whatsapp_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_event_merchant_type_received_at",
        "event",
        ["merchant_id", "type", "received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_merchant_type_received_at", table_name="event")
