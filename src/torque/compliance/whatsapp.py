"""WhatsApp template-approval gate (Blueprint Section 3, gate #2 of 2).

Pure lookup. Module 6 combines this with `Counterparty.whatsapp_opt_in`
(gate #1) and the `Merchant_Counterparty.active_wa_conversation_expires_at`
open-conversation check to form the full `SEND_WHATSAPP` guardrail and produce
`BLOCKED_BY_GUARDRAIL` / the `CONSENT_NOT_OBTAINED` / `TEMPLATE_NOT_APPROVED`
CaseEvents. None of that enforcement lives here.

META VOCABULARY GAP: `MerchantWhatsAppTemplate.approval_status` is a Meta-owned,
evolving free string. `WHATSAPP_APPROVED` below is the single source of truth for
the gate literal; only an exact, case-sensitive match satisfies the gate, so any
future/unmodelled Meta status (`PAUSED`, `DISABLED`, `IN_APPEAL`, ...) fails
closed with no schema change.
"""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from torque.enums import LegType, WhatsAppTemplateCategory
from torque.models.merchant_whatsapp_template import MerchantWhatsAppTemplate

# The ONLY Meta template status that satisfies WhatsApp gate #2. Every other
# value - PENDING, REJECTED, PAUSED, DISABLED, and any status Meta introduces
# later - fails the gate.
WHATSAPP_APPROVED = "APPROVED"


def approved_template_exists(
    session: Session,
    *,
    merchant_id: str,
    leg_type: LegType,
    category: WhatsAppTemplateCategory | str,
) -> bool:
    """True iff `merchant_id` has at least one `MerchantWhatsAppTemplate` for the
    given `leg_type` and `category` whose `approval_status` is exactly
    `WHATSAPP_APPROVED` (case-sensitive).

    Read-only: no Actions, no CaseEvents, no row mutation, no external calls, no
    enforcement.
    """
    stmt = select(
        exists().where(
            MerchantWhatsAppTemplate.merchant_id == merchant_id,
            MerchantWhatsAppTemplate.leg_type == LegType(leg_type),
            MerchantWhatsAppTemplate.category == WhatsAppTemplateCategory(category),
            MerchantWhatsAppTemplate.approval_status == WHATSAPP_APPROVED,
        )
    )
    return bool(session.scalar(stmt))
