"""0018 - escalation_resolution columns (Module 10 — Agent Console human resolution)

Additive, non-breaking. Three nullable columns on `revenue_leak_case`, no table,
no enum, no `CaseEventType` (`HUMAN_RESOLVED` and its `{resolution, agent_id}`
payload already exist — Module 1).

Blueprint §4: `ESCALATED_TO_HUMAN` "is **not** terminal — it carries
`escalation_resolution`, written by a human agent, driving the final
transition". Module 10's Agent Console (§10.8) provides that write-back:

* `escalation_resolution` VARCHAR(64)   — the human's resolution label
  (`RECOVERED_BY_HUMAN` / `PARTIALLY_RECOVERED_BY_HUMAN` / `WRITTEN_OFF`).
* `escalation_resolved_by` VARCHAR(64)  — the acting agent id.
* `escalation_resolved_at` TIMESTAMPTZ  — when it was resolved.

The `ESCALATED_TO_HUMAN → {RECOVERED, PARTIALLY_RECOVERED, WRITTEN_OFF}` edges
are already legal in `state_machine.py` (§4 diagram) — no state-machine change.
`guards.py` gains a `human_resolution_writer` context so a `→ RECOVERED`
resolution may also set `recovery_type` / `recovered_amount` (still guarded).

Revision ID: 0018_escalation_resolution
Revises: 0017_recovery_score
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_escalation_resolution"
down_revision: str | None = "0017_recovery_score"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "revenue_leak_case",
        sa.Column("escalation_resolution", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "revenue_leak_case",
        sa.Column("escalation_resolved_by", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "revenue_leak_case",
        sa.Column(
            "escalation_resolved_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("revenue_leak_case", "escalation_resolved_at")
    op.drop_column("revenue_leak_case", "escalation_resolved_by")
    op.drop_column("revenue_leak_case", "escalation_resolution")
