"""`CaseEvent` — the single audit/history mechanism for the entire system.

Blueprint Section 2.3 / Section 3: replaces `AuditLogEntry` and
`PlaybookRun.step_history` completely — both are eliminated, not deprecated.

Append-only. Enforced two ways:
* a Postgres `BEFORE UPDATE OR DELETE` trigger (migration 0005) that raises;
* a `before_flush` guard (`torque.models.guards`) that rejects dirty/deleted
  `CaseEvent` instances before they ever reach the database.

`payload` is validated against the locked schema for its `event_type`
(`torque.events.payloads`) — no `event_type` may be written without a matching
schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base
from torque.enums import Actor, CaseEventType


class CaseEvent(Base):
    __tablename__ = "case_event"

    # PK, auto-incrementing, globally ordered (a single sequence across all
    # cases — "globally ordered" per the blueprint).
    event_seq_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=False, index=True
    )
    # Reference only — NO raw PII. FK kept for integrity; nullable because a
    # CaseEvent can precede counterparty resolution in edge cases.
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("counterparty.counterparty_id"), nullable=True
    )
    event_type: Mapped[CaseEventType] = mapped_column(
        PgEnum(CaseEventType, name="case_event_type", create_type=False), nullable=False
    )
    # Typed JSON per event_type — schema locked in torque.events.payloads.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The explainability payload: *why* the engine made this choice. Renders
    # directly as the UI's "Agent Reasoning" panel (Module 9 §9.2).
    reasoning: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[Actor] = mapped_column(
        PgEnum(Actor, name="actor", create_type=False), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
