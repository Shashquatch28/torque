"""The Module 6 §6.4 human queue — orchestration.

A FIFO-per-merchant queue keyed on `case_id` (the `HumanQueueEntry` model). Three
feeders all land in the same place:

1. **low-confidence diagnoses** — Module 3 §3.3 routes them
   `DIAGNOSING → ESCALATED_TO_HUMAN` already; `sweep_escalated_to_human` picks up
   every case sitting in that status that is not yet queued (Q-H — Module 3 is
   not reopened; the sweep is origin-agnostic and simply means "this case is
   waiting for a human");
2. **escalation-ceiling cases** — enqueued inline by the runner when a run trips
   `stopping_rules.escalation_ceiling` (§6.3);
3. **broken `PromiseToPay`** — `route_broken_promise` (Part A: a broken promise
   routes to a human, *never* a harsher automated message).

The open-WhatsApp-conversation defer path (Q-F) also enqueues, with its own
reason — §6.4's list of three is not exhaustive of every "flag for human pickup"
path.

`enqueue` is idempotent against `UNIQUE(case_id)`: a re-run of any feeder, or two
feeders racing for the same case, produces exactly one row (the first reason
wins). Every query is tenant-scoped (INV-01).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.orm import Session

from torque.coordination.outreach_coordinator import priority as _priority
from torque.db.scoped import TenantScope
from torque.enums import CaseStatus, PromiseStatus
from torque.models import HumanQueueEntry, PromiseToPay, RevenueLeakCase


class HumanQueueReason(StrEnum):
    """Why a case is in the human queue. Stored as a plain string on
    `HumanQueueEntry.reason` (D-097 — the vocabulary is owned here, not as a
    Postgres enum)."""

    #: Sitting in `ESCALATED_TO_HUMAN` — low-confidence diagnosis (§3.3) or any
    #: other escalation the sweep finds not-yet-queued.
    LOW_CONFIDENCE_DIAGNOSIS = "LOW_CONFIDENCE_DIAGNOSIS"
    #: A `PlaybookRun` tripped `stopping_rules.escalation_ceiling` (§6.3).
    ESCALATION_CEILING = "ESCALATION_CEILING"
    #: A `PromiseToPay` was marked `BROKEN` (Part A — route to a human).
    PROMISE_BROKEN = "PROMISE_BROKEN"
    #: An automated WhatsApp template was suspended because a live service
    #: conversation window is open (Q-F).
    OPEN_WA_CONVERSATION = "OPEN_WA_CONVERSATION"


def enqueue(
    session: Session,
    *,
    case: RevenueLeakCase,
    reason: HumanQueueReason | str,
    priority: Decimal | None = None,
    now: datetime | None = None,
) -> HumanQueueEntry:
    """Add `case` to its merchant's human queue, or return the existing entry if
    it is already queued (idempotent — `UNIQUE(case_id)`). Does **not** commit;
    the caller owns the transaction.

    `priority` defaults to the Module 8 seam
    (`outreach_coordinator.priority(session, case)` — the authoritative
    `(probability × amount_at_risk) ÷ cost` recovery score, D-113).
    """
    now = now or datetime.now(UTC)
    scope = TenantScope(session, case.merchant_id)
    existing = session.scalars(
        scope.select(HumanQueueEntry).where(HumanQueueEntry.case_id == case.case_id)
    ).first()
    if existing is not None:
        return existing
    entry = HumanQueueEntry(
        case_id=case.case_id,
        reason=str(reason),
        priority=priority if priority is not None else _priority(session, case),
        enqueued_at=now,
    )
    scope.add(entry)
    session.flush()
    return entry


def list_for_merchant(
    session: Session, merchant_id: str, *, order: str = "priority"
) -> list[HumanQueueEntry]:
    """The merchant's queue. `order="priority"` (default) sorts by `priority`
    descending then `enqueued_at` ascending — the same economic logic as the rest
    of the system (§6.4), FIFO as the tie-break. `order="fifo"` sorts purely by
    `enqueued_at` ascending (the literal FIFO view)."""
    scope = TenantScope(session, merchant_id)
    stmt = scope.select(HumanQueueEntry)
    if order == "fifo":
        stmt = stmt.order_by(HumanQueueEntry.enqueued_at.asc())
    else:
        stmt = stmt.order_by(
            HumanQueueEntry.priority.desc(), HumanQueueEntry.enqueued_at.asc()
        )
    return list(session.scalars(stmt).all())


def remove_for_case(session: Session, case: RevenueLeakCase) -> bool:
    """Drop the human-queue entry for `case`, if any. Returns whether a row was
    removed. Called by Module 7 when reconciliation closes a case
    (`RECOVERED` / `CANCELLED`) — a resolved case no longer needs a human. This
    is a queue-consistency concern, not Agent Console behaviour (Module 10)."""
    scope = TenantScope(session, case.merchant_id)
    entry = session.scalars(
        scope.select(HumanQueueEntry).where(HumanQueueEntry.case_id == case.case_id)
    ).first()
    if entry is None:
        return False
    scope.delete(entry)
    session.flush()
    return True


def sweep_escalated_to_human(
    session: Session, merchant_id: str, *, now: datetime | None = None
) -> list[HumanQueueEntry]:
    """Feeder 1: enqueue every canonical `ESCALATED_TO_HUMAN` case for this
    merchant that is not already queued. Idempotent — a case already queued
    (e.g. by the escalation-ceiling path, keeping its `ESCALATION_CEILING`
    reason) is left untouched. Returns the entries that now exist for those
    cases."""
    now = now or datetime.now(UTC)
    scope = TenantScope(session, merchant_id)
    cases = session.scalars(
        scope.select(RevenueLeakCase)
        .where(RevenueLeakCase.status == CaseStatus.ESCALATED_TO_HUMAN)
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
    ).all()
    return [
        enqueue(
            session,
            case=case,
            reason=HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS,
            now=now,
        )
        for case in cases
    ]


def route_broken_promise(
    session: Session, promise: PromiseToPay, *, now: datetime | None = None
) -> HumanQueueEntry | None:
    """Feeder 3: a `BROKEN` `PromiseToPay` routes its case to the human queue —
    **never** a harsher automated message (Part A / D-038). No-op (returns
    ``None``) if the promise is not `BROKEN` or its case is gone.

    The `LOG_PROMISE` action that *creates* promises is a deferred Module 5
    concern; this routing hook is exercised against a directly-constructed
    `BROKEN` promise until then.
    """
    if PromiseStatus(promise.status) is not PromiseStatus.BROKEN:
        return None
    case = session.get(RevenueLeakCase, promise.case_id)
    if case is None:
        return None
    return enqueue(
        session, case=case, reason=HumanQueueReason.PROMISE_BROKEN, now=now
    )


__all__ = [
    "HumanQueueReason",
    "enqueue",
    "list_for_merchant",
    "remove_for_case",
    "route_broken_promise",
    "sweep_escalated_to_human",
]
