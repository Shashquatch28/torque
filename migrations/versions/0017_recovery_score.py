"""0017 - recovery_score columns (Module 8 — Recovery Scoring Model)

Additive, non-breaking. Three nullable columns on `revenue_leak_case`, no table,
no enum, no `CaseEventType`.

Blueprint §8 computes `(probability × amount_at_risk) ÷ cost` for every open case
and recomputes it on case creation / diagnosis completion / daily (§8.5). That
cadence needs a persisted value:

* `recovery_score`            NUMERIC(18,4) — the economic priority number, for
  `ORDER BY … DESC` (the dashboard's top-at-risk view, Module 9).
* `recovery_score_breakdown`  JSONB — the full §8.7 explainable structure
  (probability × amount ÷ cost, the "Why:" lines) so consumers render without
  recomputing.
* `recovery_score_updated_at` TIMESTAMPTZ — when the score was last refreshed.

All three are a DERIVED cache written by `torque.scoring` — no guard, no
`CaseEvent`. `HumanQueueEntry.priority` (NUMERIC(14,2), migration 0016) is
unchanged: it still stores the score at enqueue time and the daily sweep refreshes
it in place (D-113).

Revision ID: 0017_recovery_score
Revises: 0016_human_queue
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_recovery_score"
down_revision: str | None = "0016_human_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "revenue_leak_case",
        sa.Column("recovery_score", sa.Numeric(18, 4), nullable=True),
    )
    op.add_column(
        "revenue_leak_case",
        sa.Column(
            "recovery_score_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "revenue_leak_case",
        sa.Column(
            "recovery_score_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("revenue_leak_case", "recovery_score_updated_at")
    op.drop_column("revenue_leak_case", "recovery_score_breakdown")
    op.drop_column("revenue_leak_case", "recovery_score")
