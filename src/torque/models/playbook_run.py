"""`PlaybookRun` - one execution of a playbook against a case.

Blueprint Section 3 / Section 2.4. Tenant-scoped (decision G) even though
`Playbook` templates are global.

Version-pinned: `(playbook_id, playbook_version)` is a composite FK to the exact
`playbook(playbook_id, version)` row. Inserting a newer version never alters an
in-flight run - it continues on the version it started on.

`active_step_id` is a single pointer into the `steps_graph` node space - it is
**not a log**. There is NO `step_history` field; every step-entered / exited /
outcome event is a `CaseEvent` with `event_type = STEP_TRANSITIONED` (Module 5).

Milestone 4 provides the table only. Run instantiation, `active_step_id`
advancement, and `status` transitions are Module 4 / Module 5.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from torque.db.base import Base, TenantScoped
from torque.enums import PlaybookRunStatus
from torque.models.mixins import TimestampMixin, uuid_pk


class PlaybookRun(Base, TenantScoped, TimestampMixin):
    __tablename__ = "playbook_run"
    __table_args__ = (
        ForeignKeyConstraint(
            ["playbook_id", "playbook_version"],
            ["playbook.playbook_id", "playbook.version"],
        ),
    )

    run_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("merchant.merchant_id"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("revenue_leak_case.case_id"), nullable=False, index=True
    )

    # Composite FK -> playbook(playbook_id, version); pins the exact version.
    playbook_id: Mapped[str] = mapped_column(String(64), nullable=False)
    playbook_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Current position in the graph - a single pointer, NOT a log. Null before
    # the run enters its first node.
    active_step_id: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[PlaybookRunStatus] = mapped_column(
        PgEnum(PlaybookRunStatus, name="playbook_run_status", create_type=False),
        default=PlaybookRunStatus.RUNNING,
        nullable=False,
    )
