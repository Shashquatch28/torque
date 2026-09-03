"""`RevenueLeakCase` — the atomic unit. Blueprint Section 3.

Every module reads and writes this row. Notable invariants (enforced in
`torque.models.guards`, not just documented here):

* `context` is validated against the typed model for its `leg_type` at write
  time — nothing untyped is ever persisted (Blueprint Section 3).
* `network_directive_tier` only ever moves to a MORE restrictive tier
  (`TIER_1 > TIER_3 > TIER_2 > TIMED_RETRY > null`) and only via
  `torque.state_machine.apply_network_directive`.
* `recovery_type` and `recovered_amount` are written ONLY by Module 7 — the
  guard rejects any write not wrapped in `guards.module7_writer(session)`.
* `status` transitions are constrained to the locked state machine
  (`torque.state_machine`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import CaseStatus, LegType, MacTier, RecoveryType
from torque.models.mixins import TimestampMixin, uuid_pk


class RevenueLeakCase(Base, TenantScoped, TimestampMixin):
    __tablename__ = "revenue_leak_case"
    __table_args__ = (
        CheckConstraint(
            "diagnosis_confidence IS NULL OR "
            "(diagnosis_confidence >= 0 AND diagnosis_confidence <= 1)",
            name="diagnosis_confidence_unit_range",
        ),
        CheckConstraint("amount_at_risk >= 0", name="amount_at_risk_non_negative"),
        CheckConstraint(
            "recovered_amount IS NULL OR recovered_amount >= 0",
            name="recovered_amount_non_negative",
        ),
    )

    case_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )

    leg_type: Mapped[LegType] = mapped_column(
        PgEnum(LegType, name="leg_type", create_type=False), nullable=False
    )
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("event.event_id"), nullable=False
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparty.counterparty_id"), nullable=False, index=True
    )

    # Nullable FK -> SystemicEvent (wired in Milestone 3). Default RESTRICT delete
    # behaviour: a referenced SystemicEvent cannot be deleted. When set, playbook
    # execution is suppressed (SYSTEMIC_HOLD status) — that transition itself is
    # Module 2 Section 2.5, not this model.
    systemic_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("systemic_event.systemic_event_id"),
        nullable=True,
        index=True,
    )

    amount_at_risk: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    status: Mapped[CaseStatus] = mapped_column(
        PgEnum(CaseStatus, name="case_status", create_type=False),
        default=CaseStatus.DETECTED,
        nullable=False,
    )

    # Set by the Diagnosis Engine (Module 3). Enum owned by Module 3 §3.1 — a
    # plain string here on purpose.
    root_cause_code: Mapped[str | None] = mapped_column(String(64))
    root_cause_label: Mapped[str | None] = mapped_column(String(256))

    # network_directive {mac_code, tier} — stored as two discrete columns (not a
    # JSON blob) because every module checks the tier without a context parse
    # (Blueprint Section 3). Most-restrictive-tier-ever-received, non-overridable.
    network_directive_mac_code: Mapped[str | None] = mapped_column(String(8))
    network_directive_tier: Mapped[MacTier | None] = mapped_column(
        PgEnum(MacTier, name="mac_tier", create_type=False)
    )

    # Stored on every case from day one for calibration (Decision E).
    diagnosis_confidence: Mapped[float | None] = mapped_column(Float)

    # Set by the Diagnosis Engine (Module 3 §3.4) alongside root_cause_code, a
    # SEPARATE signal from diagnosis_confidence: the payday-cycle retry-timing
    # hint (e.g. "next_month_end_working_day") that Module 4 §4.3 applies only
    # when the merchant's payday_cycle_override is enabled. A symbolic label, not
    # a computed date — the concrete fire time is Module 4/5's to derive. Blueprint
    # Part A predates this diagnosis output (a Part-C-style Module-1 addition); it
    # has no other persistence home (the DIAGNOSIS_COMPLETED payload schema is
    # closed and the typed leg contexts forbid extra keys). Nullable — most root
    # causes emit no timing hint. See D-079.
    suggested_timing_adjustment: Mapped[str | None] = mapped_column(String(64))

    # Strict typed model per leg_type, validated at the ORM boundary.
    context: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Derived, read-only — denormalised from Merchant_Counterparty.in_control_cohort
    # to avoid a per-query join. Kept in sync by state_machine.sync_control_group.
    control_group: Mapped[bool | None] = mapped_column(Boolean)

    # Cross-leg dedup merge pointer (Decision D). Self-FK.
    superseded_by_case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=True
    )

    # Written ONLY by Module 7 (Reconciliation & Attribution).
    recovery_type: Mapped[RecoveryType | None] = mapped_column(
        PgEnum(RecoveryType, name="recovery_type", create_type=False)
    )
    recovered_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
