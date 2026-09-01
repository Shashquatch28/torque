"""Session-level enforcement of RevenueLeakCase invariants and CaseEvent
append-only semantics.

Wired onto `SessionLocal` in `torque.db.session`. Every session from the
sanctioned factory runs these checks at flush time.

Enforced here:
1. `CaseEvent` rows are never UPDATEd or DELETEd (append-only, Section 2.3).
2. `RevenueLeakCase.recovery_type` / `.recovered_amount` are writable only
   inside `module7_writer(session)` (Module 7 is the sole writer).
3. `RevenueLeakCase.network_directive_tier` is writable only inside
   `network_directive_writer(session)` and only toward a MORE restrictive tier
   (`TIER_1 > TIER_3 > TIER_2 > TIMED_RETRY > null`).
4. `RevenueLeakCase.context` is validated/normalised against its `leg_type`
   model on every flush — nothing untyped is ever persisted.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from sqlalchemy import event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from torque.contexts.registry import validate_context
from torque.enums import MacTier
from torque.exceptions import (
    AppendOnlyViolation,
    MonotonicityViolation,
    OwnershipViolation,
)
from torque.models.case_event import CaseEvent
from torque.models.revenue_leak_case import RevenueLeakCase

_M7_FLAG = "torque.module7_writer"
_ND_FLAG = "torque.network_directive_writer"

# Higher rank == more restrictive. Downgrades are rejected; equal is allowed
# (re-receiving the same tier on a later attempt is legitimate).
_TIER_RANK: dict[MacTier | None, int] = {
    None: 0,
    MacTier.TIMED_RETRY: 1,
    MacTier.TIER_2_CAPPED_RETRY: 2,
    MacTier.TIER_3_INSTRUMENT_DEAD: 3,
    MacTier.TIER_1_HARD_STOP: 4,
}


@contextmanager
def _flag(session: Session, key: str) -> Iterator[None]:
    previous = session.info.get(key, None)
    session.info[key] = True
    try:
        yield
    finally:
        if previous is None:
            session.info.pop(key, None)
        else:
            session.info[key] = previous


def module7_writer(session: Session) -> AbstractContextManager[None]:
    """Permit writes to `recovery_type` / `recovered_amount` within the block.

    Module 7 is the only code that should ever enter this.
    """
    return _flag(session, _M7_FLAG)


def network_directive_writer(session: Session) -> AbstractContextManager[None]:
    """Permit writes to `network_directive_tier` within the block. Used by
    `torque.state_machine.apply_network_directive`, which additionally enforces
    the monotonicity rule before mutating."""
    return _flag(session, _ND_FLAG)


def tier_rank(tier: MacTier | str | None) -> int:
    if tier is None:
        return 0
    return _TIER_RANK[MacTier(tier)]


# --- flush-time listener -----------------------------------------------------


def _before_flush(session: Session, flush_context, instances) -> None:
    for obj in session.deleted:
        if isinstance(obj, CaseEvent):
            raise AppendOnlyViolation("CaseEvent rows cannot be deleted (append-only)")

    for obj in session.dirty:
        if isinstance(obj, CaseEvent) and session.is_modified(
            obj, include_collections=False
        ):
            raise AppendOnlyViolation("CaseEvent rows are immutable (append-only)")

    m7 = bool(session.info.get(_M7_FLAG))
    nd = bool(session.info.get(_ND_FLAG))

    for obj in [*session.new, *session.dirty]:
        if isinstance(obj, RevenueLeakCase):
            _guard_case(obj, m7=m7, nd=nd)


def _guard_case(case: RevenueLeakCase, *, m7: bool, nd: bool) -> None:
    state = sa_inspect(case)

    for field in ("recovery_type", "recovered_amount"):
        if state.attrs[field].history.has_changes() and not m7:
            raise OwnershipViolation(
                f"RevenueLeakCase.{field} is written only by Module 7 "
                f"(wrap the write in guards.module7_writer(session))"
            )

    tier_hist = state.attrs["network_directive_tier"].history
    if tier_hist.has_changes():
        if not nd:
            raise OwnershipViolation(
                "RevenueLeakCase.network_directive_tier must be set via "
                "state_machine.apply_network_directive()"
            )
        old = tier_hist.deleted[0] if tier_hist.deleted else None
        new = tier_hist.added[0] if tier_hist.added else None
        if tier_rank(new) < tier_rank(old):
            raise MonotonicityViolation(
                f"network_directive tier downgrade {old} -> {new} rejected "
                f"(most-restrictive-wins, Section 4)"
            )

    normalized = validate_context(case.leg_type, case.context or {})
    if normalized != case.context:
        case.context = normalized


def register_guards(session_factory) -> None:
    if not event.contains(session_factory, "before_flush", _before_flush):
        event.listen(session_factory, "before_flush", _before_flush)
