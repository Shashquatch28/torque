"""`GuardrailEngine` — the single Module 6 facade Module 5's execution loop
consults (Blueprint §6.2 / Part C item 2).

> Module 5 executes actions and owns the atomic write; Module 6 owns the decision
> of whether an action is allowed to happen at all.

**Return shape (D-097 / Q-A).** The blueprint names the return `{ allow, block_reason? }`.
Torque deliberately returns the existing four-way `GuardDecision`
(`ALLOW` / `BLOCK` / `DEFER` / `AUTO_INSERT_PREDEBIT`) instead: Module 5 already
relies on `DEFER` (quiet-hours, the NPCI UPI peak window) and
`AUTO_INSERT_PREDEBIT` (the §5.2.3 pre-debit self-heal), and neither is
expressible as a bare boolean. This is an intentional, documented deviation — the
narrower wording is superseded, and no existing behaviour is regressed.

The facade **composes** the existing pure predicates
(`torque.execution.guardrails`, `torque.compliance.*`,
`torque.coordination.outreach_coordinator`) — it never re-implements them. The
ordered sequence is exactly Blueprint §5.2, first-failure-wins.

The live **merge** step (§5.2 list 2 item 2, "route to §4.4's merge path") is not
a `GuardDecision` — it restructures two runs into one `Action`. It is handled in
`torque.coordination.merge`, invoked from the poll batch where both jobs are
already claimed under one lock; the facade covers everything else.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from torque.coordination import outreach_coordinator as OC
from torque.coordination.human_queue import HumanQueueReason
from torque.enums import ActionType, BlockReason
from torque.execution import timing
from torque.execution.guardrails import (
    GuardDecision,
    GuardKind,
    case_under_systemic_hold,
    check_retry_guardrails,
)
from torque.models import RevenueLeakCase

_ALLOW = GuardDecision(GuardKind.ALLOW)

# Customer-contact actions that carry only the systemic-hold check (parity with
# Module 5's `check_contact_guardrails`) — a pre-debit notice is a compliance
# communication, not marketing outreach.
_CONTACT_ACTIONS: frozenset[ActionType] = OC.OUTREACH_ACTIONS | {
    ActionType.SEND_PRE_DEBIT_NOTIFICATION
}

# A permissive fallback window when a standalone caller supplies no run/rules.
_ANY_HOURS = ("00:00", "23:59")


class GuardrailEngine:
    """Namespace for the one function Module 5 calls."""

    @staticmethod
    def check(
        session: Session,
        *,
        action_type: ActionType | str,
        now: datetime,
        case: RevenueLeakCase | None = None,
        case_id=None,
        run=None,
        node: dict | None = None,
        params: dict | None = None,
    ) -> GuardDecision:
        """Run the §5.2 guardrail sequence for `action_type` and return the
        `GuardDecision` (four-way — see the module docstring).

        Pass `case` (the runner does) or `case_id` (standalone callers). `run` /
        `node` let the contact-action path compute an exact defer target and the
        quiet-hours window; `params` is the node's params dict, passed through
        untouched (Q — no new params-validation subsystem).
        """
        _ = params  # pass-through only; no validation subsystem (Q)
        if case is None and case_id is not None:
            case = session.get(RevenueLeakCase, case_id)
        if case is None:
            raise ValueError("GuardrailEngine.check needs a case or a resolvable case_id")
        at = ActionType(action_type)

        if at is ActionType.RETRY_PAYMENT:
            # §5.2 list 1 — network hard-stop → rail budget → pre-debit gap /
            # AUTO_INSERT self-heal → systemic hold. Unchanged Module 5 order;
            # the facade delegates verbatim.
            return check_retry_guardrails(session, case, now=now)

        if at in _CONTACT_ACTIONS:
            return _check_contact(session, case, at, now=now, run=run, node=node)

        return _ALLOW


def _allowed_hours(session: Session, run) -> tuple[str, str]:
    if run is None:
        return _ANY_HOURS
    from torque.policy.engine import resolve_effective_stopping_rules

    rules = resolve_effective_stopping_rules(session, run)
    return rules.allowed_hours.start, rules.allowed_hours.end


def _check_contact(
    session: Session,
    case: RevenueLeakCase,
    action_type: ActionType,
    *,
    now: datetime,
    run,
    node: dict | None,
) -> GuardDecision:
    """§5.2 list 2 — customer-contact sequence, first-failure-wins:

    1. systemic hold                     (BLOCK)
    2. cross-leg 4h quiet period         (DEFER → OUTREACH_COORDINATOR_DEFERRED)
    3. [merge eligibility — handled in torque.coordination.merge]
    4. WhatsApp gate #1 + #2             (BLOCK → CONSENT_NOT_OBTAINED / TEMPLATE_NOT_APPROVED)
    5. open-conversation suspension      (DEFER + human-queue flag)
    6. quiet-hours                       (DEFER — defer-only, Q-G)
    """
    # 1. systemic hold — applies to every contact action, pre-debit included.
    if case_under_systemic_hold(session, case):
        return GuardDecision(GuardKind.BLOCK, BlockReason.SYSTEMIC_HOLD)

    # A pre-debit notice stops here — no coordinator, no channel gate.
    if action_type not in OC.OUTREACH_ACTIONS:
        return _ALLOW

    start, end = _allowed_hours(session, run)
    offset = float((node or {}).get("timing_offset_hours", 0) or 0)

    # 2. cross-leg quiet period.
    defer_until = OC.cross_leg_quiet_period_defer(
        session, case, now=now, allowed_start=start, allowed_end=end,
        timing_offset_hours=offset,
    )
    if defer_until is not None:
        return GuardDecision(
            GuardKind.DEFER,
            block_reason=BlockReason.OUTREACH_COORDINATOR_DEFERRED,
            defer_until=defer_until,
        )

    # 4. WhatsApp channel gate (opt-in + approved template).
    if action_type is ActionType.SEND_WHATSAPP:
        reason = OC.whatsapp_gate(session, case)
        if reason is not None:
            return GuardDecision(GuardKind.BLOCK, reason)

    # 5. open-conversation suspension (WhatsApp only — the live window is a
    #    WhatsApp service-conversation concept).
    if action_type is ActionType.SEND_WHATSAPP:
        oc_defer = OC.open_conversation_defer(
            session, case, now=now, allowed_start=start, allowed_end=end
        )
        if oc_defer is not None:
            return GuardDecision(
                GuardKind.DEFER,
                block_reason=BlockReason.OUTREACH_COORDINATOR_DEFERRED,
                defer_until=oc_defer,
                human_queue_reason=str(HumanQueueReason.OPEN_WA_CONVERSATION),
            )

    # 6. quiet-hours — defer only (Q-G). The runner re-checks allowed_hours
    #    before it ever calls the facade, so in the live loop this is
    #    belt-and-braces; it matters for standalone callers.
    if run is not None and not timing.within_allowed_hours(now, start, end):
        return GuardDecision(GuardKind.DEFER)

    return _ALLOW


__all__ = ["GuardrailEngine"]
