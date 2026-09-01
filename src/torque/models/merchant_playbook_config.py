"""`MerchantPlaybookConfig` - per-merchant tuning of a global playbook.

Blueprint Section 4.2 / decision A. The playbook graph, sequencing, and template
logic stay centrally authored (`Playbook`); this row only carries a partial
`stopping_rules` override and an availability flag.

Resolution (decision 6):
* `stopping_rules_override IS NULL` (or `{}`) -> effective rules = base playbook
  `stopping_rules`;
* a non-null override -> `deep_merge(base, override)`, then full validation.

`enabled` does NOT affect rule resolution - it governs whether the playbook is
available for merchant selection / execution, a Module 4 / runtime concern.

The override is validated at flush (guard) against the **latest** published
`Playbook` version - the same path, including the UPI AutoPay `max_attempts <= 3`
ceiling, that guards the base playbook (defense-in-depth alongside
`UPIRetryBudget.hard_cap`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.models.mixins import TimestampMixin, uuid_pk


class MerchantPlaybookConfig(Base, TenantScoped, TimestampMixin):
    __tablename__ = "merchant_playbook_config"
    __table_args__ = (
        UniqueConstraint("merchant_id", "playbook_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    # Real FK to the identity anchor (decision 1) - no dangling configs.
    playbook_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("playbook_identity.playbook_id"), nullable=False
    )
    # Partial StoppingRules; nullable = "use the playbook defaults".
    stopping_rules_override: Mapped[dict | None] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
