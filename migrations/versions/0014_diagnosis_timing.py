"""0014 - diagnosis suggested_timing_adjustment (Module 3 — Diagnosis Engine)

Additive, non-breaking. One nullable column, no table, no enum.

Adds `revenue_leak_case.suggested_timing_adjustment` (VARCHAR(64), nullable) —
the payday-cycle retry-timing hint the Diagnosis Engine emits (Blueprint §3.4)
as a signal SEPARATE from `diagnosis_confidence`, read by Module 4 §4.3. Part A's
`RevenueLeakCase` reference predates this diagnosis output; it is a Part-C-style
addition to the Module-1 schema. It cannot live in the `DIAGNOSIS_COMPLETED`
CaseEvent payload (that schema is closed) nor in the typed leg contexts
(`extra="forbid"`, and `B2B_RECEIVABLE` has none), so it is a case column — the
same shape `root_cause_code` / `diagnosis_confidence` already take. See D-079.

Revision ID: 0014_diagnosis_timing
Revises: 0013_event_ingestion_index
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_diagnosis_timing"
down_revision: str | None = "0013_event_ingestion_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "revenue_leak_case",
        sa.Column("suggested_timing_adjustment", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("revenue_leak_case", "suggested_timing_adjustment")
