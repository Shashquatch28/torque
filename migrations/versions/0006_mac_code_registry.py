"""0006 - mac_code_registry (+ the 13 locked seed rows)

Blueprint Section 3: seed ONLY the verified codes 03, 21, 5C, 9G, 40, 41, 24-30
(all MASTERCARD). The larger unseeded set and every Visa equivalent are Part E
item 1 / a Module 5 pre-production checklist item - do not add them here.

Revision ID: 0006_mac_code_registry
Revises: 0005_case_event
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_mac_code_registry"
down_revision: str | None = "0005_case_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")

# (mac_code, tier, notes) - all network = MASTERCARD. Short notes; the full
# rationale for each tier is in Blueprint Section 3 / Section 4.
_SEED: list[tuple[str, str, str]] = [
    ("03", "TIER_1_HARD_STOP", "Do-not-try-again; fraud/closed acct. Fee on any retry."),
    ("21", "TIER_1_HARD_STOP", "Stop recurring; cardholder-cancelled. Fee like 03."),
    ("5C", "TIER_2_CAPPED_RETRY", "Issuer-temporary. Counts toward volume caps."),
    ("9G", "TIER_2_CAPPED_RETRY", "Same as 5C."),
    ("40", "TIER_3_INSTRUMENT_DEAD", "Single-use VCN. No fee; retry futile - ask new method."),
    ("41", "TIER_3_INSTRUMENT_DEAD", "Non-reloadable prepaid. Same as 40."),
    ("24", "TIMED_RETRY", "Retry after 1 hour"),
    ("25", "TIMED_RETRY", "Retry after 24 hours"),
    ("26", "TIMED_RETRY", "Retry after 2 days"),
    ("27", "TIMED_RETRY", "Retry after 4 days"),
    ("28", "TIMED_RETRY", "Retry after 6 days"),
    ("29", "TIMED_RETRY", "Retry after 8 days"),
    ("30", "TIMED_RETRY", "Retry after 10 days"),
]


def upgrade() -> None:
    op.create_table(
        "mac_code_registry",
        sa.Column(
            "network",
            postgresql.ENUM(name="network", create_type=False),
            primary_key=True,
        ),
        sa.Column("mac_code", sa.String(8), primary_key=True),
        sa.Column(
            "tier",
            postgresql.ENUM(name="mac_tier", create_type=False),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )

    registry = sa.table(
        "mac_code_registry",
        sa.column("network", postgresql.ENUM(name="network", create_type=False)),
        sa.column("mac_code", sa.String),
        sa.column("tier", postgresql.ENUM(name="mac_tier", create_type=False)),
        sa.column("notes", sa.Text),
    )
    op.bulk_insert(
        registry,
        [
            {"network": "MASTERCARD", "mac_code": code, "tier": tier, "notes": notes}
            for code, tier, notes in _SEED
        ],
    )


def downgrade() -> None:
    op.drop_table("mac_code_registry")
