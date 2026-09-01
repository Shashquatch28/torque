"""`Counterparty` — the single source of PII in the entire system.

Blueprint Section 2.2: `name`, `phone`, `email` live here and NOWHERE else.
Every other table references `counterparty_id` only. Erasure = null these three
fields on one row; all downstream history stays structurally intact and simply
de-identifies.

Global scope: `Counterparty` does NOT carry `merchant_id` (confirmed R3).
Per-merchant relationship data lives on `Merchant_Counterparty`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base
from torque.enums import LanguagePref
from torque.models.mixins import TimestampMixin, uuid_pk


class Counterparty(Base, TimestampMixin):
    __tablename__ = "counterparty"

    counterparty_id: Mapped[uuid.UUID] = uuid_pk()

    # --- the only raw PII in Torque; nullable so erasure can null them ---
    name: Mapped[str | None] = mapped_column(String(256))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))

    # --- consent (Blueprint Section 2.2) ---
    # Gate #1 of 2 for WhatsApp (gate #2 is template approval).
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Purpose-limitation gate under DPDP — SEPARATE from whatsapp_opt_in.
    # Pre-seeded true in demo synthetic data; a production onboarding gate.
    payment_failure_nudge_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    language_pref: Mapped[LanguagePref] = mapped_column(
        PgEnum(LanguagePref, name="language_pref", create_type=False),
        default=LanguagePref.HINGLISH,
        nullable=False,
    )
    # Timestamped opt-in/opt-out history. Entries carry no raw PII — only the
    # action, the scope, and when. Shape:
    #   {"action": "opt_in"|"opt_out"|"erased", "scope": "whatsapp"|
    #    "payment_failure_nudge"|"pii", "at": <iso8601>, "source": <str>}
    # (R6 resolved to JSONB for Milestone 1; promotable to a child table later
    #  with no change to the erasure model.)
    consent_log: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # -----------------------------------------------------------------

    def redact_pii(self, *, source: str = "erasure_request") -> None:
        """DPDP erasure mechanism. Nulls the three PII fields and appends an
        audit entry to `consent_log`. The request-*intake* flow is design-only
        for the demo (Decision H); this is the mechanical operation it calls.
        """
        self.name = None
        self.phone = None
        self.email = None
        entry = {
            "action": "erased",
            "scope": "pii",
            "at": datetime.now(UTC).isoformat(),
            "source": source,
        }
        # Reassign (don't mutate in place) so SQLAlchemy tracks the change.
        self.consent_log = [*(self.consent_log or []), entry]
