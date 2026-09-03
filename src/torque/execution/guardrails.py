"""Execution-time guardrails — Blueprint §5.2 (the checks Module 5 owns).

Per the confirmed Module 5/6 line: Module 5 runs the retry-rail, network-hard-stop,
pre-debit, and systemic-hold checks (and treats quiet-hours / execution windows as
*defers*, per §5.2.5); the canonical `GuardrailEngine.check()` facade, the Outreach
Coordinator merge/quiet-period policy, and the WhatsApp consent/template gate are
**Module 6** (deferred, D-092). Since the demo executor performs no real contact,
the outstanding Module-6 contact gates are safe to defer.

Results are one of: ALLOW (fire it), BLOCK (write `ACTION_BLOCKED`, follow the
`on_blocked` edge — §5.1), DEFER (reschedule the timer, don't fire — a *when*
constraint, never a failure), or AUTO_INSERT_PREDEBIT (the §5.2.3 self-heal: send
the pre-debit notice now, re-arm the retry 24 h out instead of dead-ending).

First-failure-wins / short-circuits, in the §5.2 order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

from sqlalchemy import func
from sqlalchemy.orm import Session

from torque.compliance.pre_debit import PRE_DEBIT_MIN_GAP_HOURS, gap_satisfied
from torque.compliance.retry_rails import (
    card_retry_within_budget,
    nach_retry_eligible,
    upi_attempt_gate_open,
    within_upi_execution_window,
)
from torque.db.scoped import TenantScope
from torque.enums import (
    ActionOutcome,
    ActionType,
    BlockReason,
    ClearingCycleStatus,
    LegType,
    MacTier,
    MandateType,
)
from torque.ingestion import payloads
from torque.models import (
    Action,
    CardRetryBudget,
    Event,
    NACHRetryPolicy,
    RevenueLeakCase,
    SystemicEvent,
    UPIRetryBudget,
)


class GuardKind(Enum):
    ALLOW = auto()
    BLOCK = auto()
    DEFER = auto()
    AUTO_INSERT_PREDEBIT = auto()


@dataclass(frozen=True)
class GuardDecision:
    kind: GuardKind
    block_reason: BlockReason | None = None
    #: AUTO_INSERT_PREDEBIT: the 1-indexed retry attempt the notice must cover.
    predebit_attempt_number: int | None = None


_ALLOW = GuardDecision(GuardKind.ALLOW)
_HARD_STOP_TIERS = frozenset({MacTier.TIER_1_HARD_STOP, MacTier.TIER_3_INSTRUMENT_DEAD})


# --- shared helpers ----------------------------------------------------------


def case_under_systemic_hold(session: Session, case: RevenueLeakCase) -> bool:
    """§5.2.4: is the case under an **unresolved** `SystemicEvent`? Tenant-scoped
    — a merchant's hold never reads across tenants."""
    if case.systemic_event_id is None:
        return False
    event = TenantScope(session, case.merchant_id).get(SystemicEvent, case.systemic_event_id)
    return event is not None and event.resolved_at is None


def executed_retry_count(session: Session, case: RevenueLeakCase) -> int:
    """Prior RETRY_PAYMENT actions actually executed for this case (blocked ones
    do not count) — the basis for the 1-indexed next-attempt number."""
    return int(
        session.scalar(
            TenantScope(session, case.merchant_id)
            .select(Action)
            .where(Action.primary_case_id == case.case_id)
            .where(Action.action_type == ActionType.RETRY_PAYMENT)
            .where(Action.outcome != ActionOutcome.BLOCKED_BY_GUARDRAIL)
            .with_only_columns(func.count())
        )
        or 0
    )


def _card_token_hash(session: Session, case: RevenueLeakCase) -> str | None:
    """The Razorpay tokenised card reference for a payment case, read from its
    source Event (tenant-scoped) — the `CardRetryBudget` key. Never a PAN."""
    event = TenantScope(session, case.merchant_id).get(Event, case.source_event_id)
    if event is None:
        return None
    return payloads.card_instrument_ref(event.raw_payload or {})


def _mandate_id(case: RevenueLeakCase) -> str:
    return (case.context or {}).get("mandate_id") or ""


# --- RETRY_PAYMENT (§5.2 first list) -----------------------------------------


def check_retry_guardrails(
    session: Session, case: RevenueLeakCase, *, now: datetime
) -> GuardDecision:
    """The §5.2 RETRY_PAYMENT sequence Module 5 owns:
    1 network hard-stop → 2 rail budget → 3 pre-debit (subscription) → 4 systemic.
    Quiet-hours (§5.2.5) is a scheduler defer, handled outside this function.
    """
    leg = LegType(case.leg_type)

    # 1. Network hard-stop (TIER_1 / TIER_3): a card-network do-not-retry.
    tier = case.network_directive_tier
    if tier is not None and MacTier(tier) in _HARD_STOP_TIERS:
        return GuardDecision(GuardKind.BLOCK, BlockReason.NETWORK_HARD_STOP)

    # 2. Rail-specific budget.
    mandate_type = _mandate_type_of(case)
    decision = _check_rail_budget(session, case, leg=leg, mandate_type=mandate_type, now=now)
    if decision.kind is not GuardKind.ALLOW:
        return decision

    # 3. Pre-debit 24h gap — subscription retries only (RBI e-mandate). Self-heals
    #    by auto-inserting a SEND_PRE_DEBIT_NOTIFICATION rather than dead-ending.
    if leg is LegType.SUBSCRIPTION_FAILURE:
        next_attempt = executed_retry_count(session, case) + 1
        if not gap_satisfied(
            session, case_id=case.case_id, next_attempt_number=next_attempt, now=now
        ):
            return GuardDecision(
                GuardKind.AUTO_INSERT_PREDEBIT, predebit_attempt_number=next_attempt
            )

    # 4. Systemic hold.
    if case_under_systemic_hold(session, case):
        return GuardDecision(GuardKind.BLOCK, BlockReason.SYSTEMIC_HOLD)

    return _ALLOW


def _mandate_type_of(case: RevenueLeakCase) -> MandateType | None:
    if LegType(case.leg_type) is not LegType.SUBSCRIPTION_FAILURE:
        return None
    raw = (case.context or {}).get("mandate_type")
    return MandateType(raw) if raw else None


def _check_rail_budget(
    session: Session,
    case: RevenueLeakCase,
    *,
    leg: LegType,
    mandate_type: MandateType | None,
    now: datetime,
) -> GuardDecision:
    scope = TenantScope(session, case.merchant_id)

    # UPI AutoPay — attempt-count gate (hard cap) + execution-window gate.
    if mandate_type is MandateType.UPI_AUTOPAY:
        budget = session.scalars(
            scope.select(UPIRetryBudget).where(UPIRetryBudget.mandate_id == _mandate_id(case))
        ).first()
        attempts = budget.attempts_used if budget is not None else 0
        cancelled = budget.mandate_cancelled_at if budget is not None else None
        if not upi_attempt_gate_open(attempts_used=attempts, mandate_cancelled_at=cancelled):
            return GuardDecision(GuardKind.BLOCK, BlockReason.UPI_RETRY_CAP_EXCEEDED)
        if not within_upi_execution_window(now):
            # A *when* constraint, not a failure — defer past the NPCI peak window.
            return GuardDecision(GuardKind.DEFER, BlockReason.UPI_EXECUTION_WINDOW_CLOSED)
        return _ALLOW

    # NACH — clearing-cycle status + self-imposed representment ceiling.
    if mandate_type is MandateType.NACH:
        policy = session.scalars(
            scope.select(NACHRetryPolicy).where(NACHRetryPolicy.mandate_id == _mandate_id(case))
        ).first()
        if policy is None:
            return _ALLOW  # nothing seeded → no ceiling to enforce yet
        eligible = nach_retry_eligible(
            clearing_cycle_status=ClearingCycleStatus(policy.clearing_cycle_status),
            dishonour_count_this_fy=policy.dishonour_count_this_fy,
            retry_eligible_after=policy.retry_eligible_after,
            ceiling=_nach_ceiling(),
            as_of=now.date(),
        )
        if not eligible:
            return GuardDecision(GuardKind.BLOCK, BlockReason.NACH_CEILING_REACHED)
        return _ALLOW

    # CARD (payment leg, or subscription card mandate) — Mastercard dual-window.
    token = _card_token_hash(session, case)
    if token is None:
        return _ALLOW  # no card instrument reference → nothing to meter
    budget = session.scalars(
        scope.select(CardRetryBudget).where(CardRetryBudget.card_token_hash == token)
    ).first()
    if budget is None:
        return _ALLOW
    if budget.hard_stop:
        return GuardDecision(GuardKind.BLOCK, BlockReason.NETWORK_HARD_STOP)
    if not card_retry_within_budget(
        attempts_used_24h=budget.attempts_used_24h,
        attempts_used_30d=budget.attempts_used_30d,
        hard_stop=budget.hard_stop,
    ):
        return GuardDecision(GuardKind.BLOCK, BlockReason.CARD_NETWORK_LIMIT)
    return _ALLOW


def _nach_ceiling() -> int:
    from torque.config import get_policy

    return get_policy().nach_representment_ceiling_default


# --- customer-contact actions (§5.2 second list) -----------------------------


def check_contact_guardrails(
    session: Session, case: RevenueLeakCase, *, now: datetime
) -> GuardDecision:
    """The customer-contact sequence — the part Module 5 owns is the §5.2.1
    systemic-hold check. The Outreach Coordinator (quiet-period / merge) and the
    WhatsApp consent+template gate are Module 6 (deferred, D-092). Quiet-hours
    (§5.2.4) is a scheduler defer, handled outside this function."""
    if case_under_systemic_hold(session, case):
        return GuardDecision(GuardKind.BLOCK, BlockReason.SYSTEMIC_HOLD)
    return _ALLOW


__all__ = [
    "GuardDecision",
    "GuardKind",
    "PRE_DEBIT_MIN_GAP_HOURS",
    "case_under_systemic_hold",
    "check_contact_guardrails",
    "check_retry_guardrails",
    "executed_retry_count",
]
