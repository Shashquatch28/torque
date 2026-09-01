"""`PlaybookIdentity` - stable database-level identity for globally versioned
playbooks (decision 1).

Intentionally minimal and product-curated: one row per logical playbook,
`playbook_id` a human-readable slug (`card_hard_decline_tier1`,
`upi_autopay_standard`). It is the FK anchor for both `playbook` version rows
and `merchant_playbook_config`, so a merchant config can never dangle.

Global scope - NOT tenant-scoped. Effectively immutable (the PK is its only
data); deletion is blocked by FK RESTRICT while any child rows exist.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base


class PlaybookIdentity(Base):
    __tablename__ = "playbook_identity"

    playbook_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
