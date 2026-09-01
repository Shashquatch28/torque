"""`SystemicEvent` - Blueprint Section 3 / Decision J.

Detects outage-scale failure spikes so individual-case outreach can be
suppressed during them. **This milestone is schema + pure predicates only** -
the 60-second detection job, failure-rate rollups, rolling-baseline computation,
`SYSTEMIC_HOLD` case transitions, and batch re-queue on resolution are all
Module 2 Section 2.5.

Two independent detection tiers (`scope`):
* `ISSUER_SPECIFIC` - one bank/network; `issuer_code` and/or `network` names it.
* `NETWORK_WIDE`   - aggregate spike across all issuers; both may be null.

The compound threshold rule and the sustain-window resolution rule live in
`torque.compliance.systemic` as pure predicates.

`merchant_id` + tenant scoping (confirmed decision A): thresholds and baselines
are per-merchant ("the merchant's own historical aggregate baseline").
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import Network, SystemicScope
from torque.models.mixins import TimestampMixin, uuid_pk


class SystemicEvent(Base, TenantScoped, TimestampMixin):
    __tablename__ = "systemic_event"
    __table_args__ = (
        CheckConstraint(
            "failure_rate_at_detection >= 0", name="failure_rate_non_negative"
        ),
        CheckConstraint(
            "affected_case_count >= 0", name="affected_case_count_non_negative"
        ),
        # Coherence (decision E): an ISSUER_SPECIFIC event must name a target;
        # a NETWORK_WIDE event may leave both null.
        CheckConstraint(
            "scope = 'NETWORK_WIDE' OR issuer_code IS NOT NULL OR network IS NOT NULL",
            name="issuer_specific_names_a_target",
        ),
    )

    systemic_event_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )

    # Which bank/network is affected; nullable when scope = NETWORK_WIDE.
    issuer_code: Mapped[str | None] = mapped_column(String(32))
    network: Mapped[Network | None] = mapped_column(
        PgEnum(Network, name="network", create_type=False)
    )

    scope: Mapped[SystemicScope] = mapped_column(
        PgEnum(SystemicScope, name="systemic_scope", create_type=False), nullable=False
    )
    # Failures/min when the threshold was crossed.
    failure_rate_at_detection: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Nullable - written only after the sustain window (see compliance.systemic).
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Denormalised count for reporting; populated by Module 2.
    affected_case_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
