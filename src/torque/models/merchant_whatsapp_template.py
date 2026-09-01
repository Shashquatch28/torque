"""`MerchantWhatsAppTemplate` - Blueprint Section 3 (WhatsApp gate #2 of 2).

Per-merchant Meta/WABA template approvals. Module 6's `SEND_WHATSAPP` guardrail
combines `torque.compliance.whatsapp.approved_template_exists` (gate #2) with
`Counterparty.whatsapp_opt_in` (gate #1) and the
`Merchant_Counterparty.active_wa_conversation_expires_at` open-conversation check
to produce `BLOCKED_BY_GUARDRAIL` / the `CONSENT_NOT_OBTAINED` /
`TEMPLATE_NOT_APPROVED` CaseEvents. That enforcement is Module 6 - this milestone
provides the table + the pure lookup only.

**META VOCABULARY GAP (intentional):** `approval_status` is a plain `String`,
NOT an enum, and carries no CHECK. Meta owns and evolves this vocabulary
(`APPROVED`, `PENDING`, `REJECTED`, `PAUSED`, `DISABLED`, `IN_APPEAL`,
`LIMIT_EXCEEDED`, ...). Meta's status is stored verbatim. The invariant is NOT
"status must belong to a known list" - it is:

    approval_status == "APPROVED"  ->  gate passes
    anything else (incl. future/unmodelled Meta statuses)  ->  gate FAILS CLOSED

This lets real Meta integration persist any status without a schema migration
and without accidentally satisfying the compliance gate.

`category` IS an enum (`WhatsAppTemplateCategory`: UTILITY | MARKETING);
`AUTHENTICATION` is a deferred category (explicit `ALTER TYPE` migration if ever
needed). There is NO `approval_status` transition guard - Meta-owned statuses
change freely.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import LegType, WhatsAppTemplateCategory
from torque.models.mixins import TimestampMixin


class MerchantWhatsAppTemplate(Base, TenantScoped, TimestampMixin):
    __tablename__ = "merchant_whatsapp_template"
    __table_args__ = (
        Index(
            "ix_merchant_whatsapp_template_gate",
            "merchant_id",
            "leg_type",
            "category",
        ),
    )

    # Meta/WABA template id - external identifier owned by Meta.
    template_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    template_name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[WhatsAppTemplateCategory] = mapped_column(
        PgEnum(
            WhatsAppTemplateCategory,
            name="whatsapp_template_category",
            create_type=False,
        ),
        nullable=False,
    )
    # Meta-owned, evolving vocabulary - plain String, no enum, no CHECK.
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    leg_type: Mapped[LegType] = mapped_column(
        PgEnum(LegType, name="leg_type", create_type=False), nullable=False
    )
