"""0001 — create all Postgres ENUM types

Every enum in `torque.enums` gets a native Postgres type here so that the
0002-0005 table migrations (and later module migrations) only *reference* them
with ``create_type=False``. One place to look for the enum vocabulary.

Revision ID: 0001_enums
Revises:
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import postgresql

from torque.enums import (
    ActionOutcome,
    ActionType,
    Actor,
    BlockReason,
    CaseEventType,
    CaseStatus,
    ClearingCycleStatus,
    HardStopReason,
    LanguagePref,
    LegType,
    MacTier,
    MandateType,
    Network,
    PaymentLinkStatus,
    PaymentMethodAttempted,
    PlaybookRunStatus,
    PromiseStatus,
    RecoveryType,
    SystemicScope,
)

revision: str = "0001_enums"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_TYPES: list[tuple[str, type]] = [
    ("leg_type", LegType),
    ("mandate_type", MandateType),
    ("case_status", CaseStatus),
    ("mac_tier", MacTier),
    ("network", Network),
    ("action_type", ActionType),
    ("action_outcome", ActionOutcome),
    ("block_reason", BlockReason),
    ("case_event_type", CaseEventType),
    ("actor", Actor),
    ("recovery_type", RecoveryType),
    ("promise_status", PromiseStatus),
    ("playbook_run_status", PlaybookRunStatus),
    ("payment_link_status", PaymentLinkStatus),
    ("payment_method_attempted", PaymentMethodAttempted),
    ("hard_stop_reason", HardStopReason),
    ("clearing_cycle_status", ClearingCycleStatus),
    ("systemic_scope", SystemicScope),
    ("language_pref", LanguagePref),
]


def upgrade() -> None:
    bind = op.get_bind()
    for name, enum_cls in ENUM_TYPES:
        postgresql.ENUM(*[m.value for m in enum_cls], name=name).create(
            bind, checkfirst=True
        )


def downgrade() -> None:
    bind = op.get_bind()
    for name, _ in reversed(ENUM_TYPES):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
