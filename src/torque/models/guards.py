"""Session-level enforcement of model invariants at flush time.

Wired onto `SessionLocal` in `torque.db.session`. Every session from the
sanctioned factory runs these checks — there is no bypass through a plain
`session.add()`.

Enforced here:
1. `CaseEvent` rows are never UPDATEd or DELETEd (append-only, Section 2.3).
2. `RevenueLeakCase.recovery_type` / `.recovered_amount` are writable only
   inside `module7_writer(session)` (Module 7 reconciliation) or
   `human_resolution_writer(session)` (Module 10 Agent Console human
   resolution) — never a casual write.
3. `RevenueLeakCase.network_directive_tier` is writable only inside
   `network_directive_writer(session)` and only toward a MORE restrictive tier.
4. `RevenueLeakCase.context` is validated/normalised against its `leg_type`
   model on every flush — nothing untyped is ever persisted.
5. `Playbook` versions are append-only (never UPDATEd / DELETEd) and their
   `steps_graph` / `stopping_rules` are validated + normalised on insert
   (Section 2.4 / Section 4.2).
6. `MerchantPlaybookConfig.stopping_rules_override`, merged onto the latest
   `Playbook` version, is validated on every insert/update — the same path,
   including the UPI AutoPay `max_attempts <= 3` ceiling, that guards the base
   playbook (Section 4.2 defense-in-depth).
7. `ActionCase` attribution: every `Action` has >= 1 row; exactly one
   `is_primary`; the `is_primary` row's `case_id` == `Action.primary_case_id`;
   Σ `credit_weight` == Decimal("1.00000") (exact); the complete set is present
   in the same flush (Milestone 5).
8. `Action` <-> `CaseEvent` atomicity: every new `Action` must be accompanied,
   in the same flush, by a new `CaseEvent` for `Action.primary_case_id` whose
   `event_type` matches the outcome (`ACTION_BLOCKED` iff
   `BLOCKED_BY_GUARDRAIL`, else `ACTION_EXECUTED`) and whose `payload.action_id`
   equals the Action's id — the explicit correlation value.

   INTENTIONAL DEVIATION (Milestone 5): Blueprint Section 2.3 frames Action <->
   CaseEvent atomicity as "a Module 5 code-review checklist item, not a design
   aspiration". Torque strengthens it to a structurally enforced invariant here,
   for the same reason tenancy, append-only history, typed contexts, and
   Playbook immutability are guard-enforced: code review is not an invariant and
   audit integrity is critical. `CaseEvent` gains NO `action_id` column and NO
   FK to `Action` — the correlation lives only in the event payload string.
9. `PromiseToPay.status`: a new row must be `PENDING`; any status change on an
   existing row must be a legal transition (`PENDING -> KEPT` / `PENDING ->
   BROKEN`; `KEPT` / `BROKEN` terminal). Same graph as `torque.promises`
   (Milestone 6a). No `CaseEvent` is written.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal

from sqlalchemy import event, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from torque.contexts.registry import validate_context
from torque.enums import ActionOutcome, CaseEventType, MacTier, PromiseStatus
from torque.exceptions import (
    ActionAtomicityError,
    ActionCaseInvariantError,
    AppendOnlyViolation,
    MonotonicityViolation,
    OwnershipViolation,
    PlaybookNotFoundError,
    PromiseTransitionError,
)
from torque.models.case_event import CaseEvent
from torque.models.merchant_playbook_config import MerchantPlaybookConfig
from torque.models.playbook import Playbook
from torque.models.revenue_leak_case import RevenueLeakCase
from torque.promises import assert_promise_transition

# `Action` / `ActionCase` are imported lazily inside the flush listener:
# `torque.models.__init__` imports `action` first, and this module is pulled in
# (via `torque.db.session`) mid-way through that import, so a top-level import
# here would be circular.

_FULL_WEIGHT = Decimal("1")

_M7_FLAG = "torque.module7_writer"
_ND_FLAG = "torque.network_directive_writer"
_HR_FLAG = "torque.human_resolution_writer"

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


def human_resolution_writer(session: Session) -> AbstractContextManager[None]:
    """Permit writes to `recovery_type` / `recovered_amount` within the block for
    a Module 10 Agent Console human resolution (Blueprint §4 / §10.8).

    `ESCALATED_TO_HUMAN` is not terminal — a human agent drives its final
    transition, and a `→ RECOVERED` / `→ PARTIALLY_RECOVERED` resolution must
    record the recovered amount (and credit it as `AGENT_ASSISTED` — the human
    agent is Torque's). Only `torque.agent_console.resolve` should enter this.
    Reconciliation (Module 7) keeps its own `module7_writer` gate; this is a
    parallel, equally deliberate entry point, not a widening of Module 7."""
    return _flag(session, _HR_FLAG)


def tier_rank(tier: MacTier | str | None) -> int:
    if tier is None:
        return 0
    return _TIER_RANK[MacTier(tier)]


# --- flush-time listener -----------------------------------------------------


def _before_flush(session: Session, flush_context, instances) -> None:
    for obj in session.deleted:
        if isinstance(obj, CaseEvent):
            raise AppendOnlyViolation("CaseEvent rows cannot be deleted (append-only)")
        if isinstance(obj, Playbook):
            raise AppendOnlyViolation(
                "Playbook versions cannot be deleted (append-only, Section 2.4)"
            )

    for obj in session.dirty:
        if isinstance(obj, CaseEvent) and session.is_modified(
            obj, include_collections=False
        ):
            raise AppendOnlyViolation("CaseEvent rows are immutable (append-only)")
        if isinstance(obj, Playbook) and session.is_modified(
            obj, include_collections=False
        ):
            raise AppendOnlyViolation(
                "Playbook versions are immutable — publish a new version instead "
                "(append-only, Section 2.4)"
            )

    m7 = bool(session.info.get(_M7_FLAG))
    nd = bool(session.info.get(_ND_FLAG))
    hr = bool(session.info.get(_HR_FLAG))

    from torque.models.action import Action
    from torque.models.action_case import ActionCase
    from torque.models.promise_to_pay import PromiseToPay

    new_action_ids = {a.action_id for a in session.new if isinstance(a, Action)}

    for obj in [*session.new, *session.dirty]:
        if isinstance(obj, RevenueLeakCase):
            _guard_case(obj, m7=m7, nd=nd, hr=hr)
        elif isinstance(obj, Playbook) and obj in session.new:
            _guard_playbook(obj)
        elif isinstance(obj, MerchantPlaybookConfig):
            _guard_merchant_playbook_config(session, obj)
        elif isinstance(obj, Action) and obj in session.new:
            _guard_action_write(session, obj)
        elif isinstance(obj, PromiseToPay):
            _guard_promise_to_pay(obj, is_new=obj in session.new)

    # ActionCase edits on already-persisted Actions (e.g. Module 7 re-weighting).
    touched = {
        ac.action_id
        for bucket in (session.new, session.dirty, session.deleted)
        for ac in bucket
        if isinstance(ac, ActionCase)
    }
    for aid in touched - new_action_ids:
        action = session.get(Action, aid)
        if action is None:
            raise ActionCaseInvariantError(
                f"ActionCase rows reference unknown action_id {aid}"
            )
        _validate_action_case_set(session, aid, action.primary_case_id)


def _guard_case(case: RevenueLeakCase, *, m7: bool, nd: bool, hr: bool = False) -> None:
    state = sa_inspect(case)

    for field in ("recovery_type", "recovered_amount"):
        if state.attrs[field].history.has_changes() and not (m7 or hr):
            raise OwnershipViolation(
                f"RevenueLeakCase.{field} is written only by Module 7 "
                f"reconciliation (guards.module7_writer) or a Module 10 Agent "
                f"Console human resolution (guards.human_resolution_writer)"
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


def _guard_playbook(pb: Playbook) -> None:
    from torque.playbooks.validation import validate_playbook

    graph, rules = validate_playbook(
        leg_type=pb.leg_type,
        mandate_type=pb.mandate_type,
        steps_graph=pb.steps_graph or {},
        stopping_rules=pb.stopping_rules or {},
    )
    pb.steps_graph = graph
    pb.stopping_rules = rules


def _guard_merchant_playbook_config(
    session: Session, cfg: MerchantPlaybookConfig
) -> None:
    from torque.playbooks.validation import validate_merchant_playbook_config

    latest = session.scalars(
        select(Playbook)
        .where(Playbook.playbook_id == cfg.playbook_id)
        .order_by(Playbook.version.desc())
        .limit(1)
    ).first()
    if latest is None:
        raise PlaybookNotFoundError(
            f"MerchantPlaybookConfig references playbook_id {cfg.playbook_id!r} "
            f"which has no published version to validate the override against"
        )

    normalised = validate_merchant_playbook_config(
        latest_leg_type=latest.leg_type,
        latest_mandate_type=latest.mandate_type,
        latest_stopping_rules=latest.stopping_rules,
        override=cfg.stopping_rules_override,
    )
    if normalised != cfg.stopping_rules_override:
        cfg.stopping_rules_override = normalised


def _validate_action_case_set(session: Session, action_id, primary_case_id) -> None:
    """Every `Action` has >= 1 `ActionCase`; exactly one `is_primary`; that row's
    `case_id` == `Action.primary_case_id`; Σ `credit_weight` == 1.00000 (exact
    Decimal). The full set = pending new rows + persisted rows - pending deletes.
    """
    from torque.models.action_case import ActionCase

    deleted = {
        id(ac)
        for ac in session.deleted
        if isinstance(ac, ActionCase) and ac.action_id == action_id
    }
    rows = [
        ac
        for ac in session.new
        if isinstance(ac, ActionCase) and ac.action_id == action_id
    ]
    rows += [
        ac
        for ac in session.scalars(
            select(ActionCase).where(ActionCase.action_id == action_id)
        ).all()
        if id(ac) not in deleted
    ]

    if not rows:
        raise ActionCaseInvariantError(
            f"Action {action_id} has no ActionCase attribution rows — every "
            f"Action requires at least one (Milestone 5)"
        )
    primaries = [ac for ac in rows if ac.is_primary]
    if len(primaries) != 1:
        raise ActionCaseInvariantError(
            f"Action {action_id} must have exactly one is_primary ActionCase "
            f"(has {len(primaries)})"
        )
    if primaries[0].case_id != primary_case_id:
        raise ActionCaseInvariantError(
            f"the is_primary ActionCase for action {action_id} must reference "
            f"Action.primary_case_id ({primary_case_id}), not {primaries[0].case_id}"
        )
    total = sum(
        (Decimal(str(ac.credit_weight)) for ac in rows), Decimal("0")
    )
    if total != _FULL_WEIGHT:
        raise ActionCaseInvariantError(
            f"ActionCase credit_weight for action {action_id} must sum to exactly "
            f"1.00000 (got {total})"
        )


def _guard_action_write(session: Session, action) -> None:
    _validate_action_case_set(session, action.action_id, action.primary_case_id)

    want = (
        CaseEventType.ACTION_BLOCKED
        if ActionOutcome(action.outcome) is ActionOutcome.BLOCKED_BY_GUARDRAIL
        else CaseEventType.ACTION_EXECUTED
    )
    aid = str(action.action_id)
    for ce in session.new:
        if not isinstance(ce, CaseEvent):
            continue
        if CaseEventType(ce.event_type) is not want:
            continue
        if ce.case_id != action.primary_case_id:
            continue
        if (ce.payload or {}).get("action_id") == aid:
            return

    raise ActionAtomicityError(
        f"Action {aid} was written without a correlated {want.value} CaseEvent "
        f"(case_id={action.primary_case_id}, payload.action_id={aid}) in the same "
        f"transaction (Section 2.3) — use torque.events.write_action_and_event"
    )


def _guard_promise_to_pay(promise, *, is_new: bool) -> None:
    """Enforce the same PromiseToPay.status graph as `torque.promises`: a new row
    must be PENDING; any status change on an existing row must be a legal
    transition (PENDING -> KEPT / PENDING -> BROKEN)."""
    if is_new:
        # `status` may still be None pre-flush (the column default is applied at
        # INSERT); None means "will be PENDING", which is fine.
        raw = promise.status
        effective = PromiseStatus.PENDING if raw is None else PromiseStatus(raw)
        if effective is not PromiseStatus.PENDING:
            raise PromiseTransitionError(
                f"a PromiseToPay is created PENDING (got {promise.status}); "
                f"advance it with torque.promises.transition_promise()"
            )
        return

    hist = sa_inspect(promise).attrs["status"].history
    if not hist.has_changes():
        return
    old = hist.deleted[0] if hist.deleted else None
    new = hist.added[0] if hist.added else None
    if old is None:
        return
    assert_promise_transition(PromiseStatus(old), PromiseStatus(new))


def register_guards(session_factory) -> None:
    if not event.contains(session_factory, "before_flush", _before_flush):
        event.listen(session_factory, "before_flush", _before_flush)
