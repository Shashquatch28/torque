"""The Outreach Coordinator — Blueprint Part A §5 (operationally owned by Module 6,
§6.1).

Pure decision helpers, no side effects: priority, the 4-hour cross-leg quiet
period, open-conversation suspension, and the two WhatsApp gates. The
`GuardrailEngine` facade (`torque.coordination.guardrail_engine`) composes these
in the §5.2 order; the live merge path lives in `torque.coordination.merge`
(it needs the runner's advance/finalize helpers and so is kept separate to avoid
an import cycle).

Every query is tenant-scoped (INV-01).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from torque.compliance.whatsapp import approved_template_exists
from torque.config import get_policy
from torque.db.scoped import TenantScope
from torque.enums import ActionOutcome, ActionType, BlockReason, LegType, WhatsAppTemplateCategory
from torque.execution import timing
from torque.models import (
    Action,
    Counterparty,
    MerchantCounterparty,
    RevenueLeakCase,
)

#: Customer-contact actions the coordinator + WhatsApp/channel gate apply to
#: (Blueprint §5.2 list 2). `SEND_PRE_DEBIT_NOTIFICATION` is deliberately absent —
#: it is a compliance notice, not marketing outreach, and is only ever subject to
#: the systemic-hold check (parity with Module 5's `check_contact_guardrails`).
OUTREACH_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.SEND_WHATSAPP,
        ActionType.SEND_EMAIL,
        ActionType.SEND_SMS,
        ActionType.GENERATE_PAYMENT_LINK,
    }
)

# Recovery / dunning outreach is transactional, not promotional — the WhatsApp
# gate looks for an approved *UTILITY* template for the leg. A per-node category
# override is future work (the catalog nodes carry no category today).
_OUTREACH_TEMPLATE_CATEGORY = WhatsAppTemplateCategory.UTILITY


# --- priority (Module 8 seam — Q-B) ----------------------------------------


def priority(case: RevenueLeakCase) -> Decimal:
    """The economic score the Outreach Coordinator and the human queue order by.

    **Module 8 seam.** The real score is Module 8's
    `(probability × amount_at_risk) ÷ cost` (Blueprint Part A §5 / §8). Module 8
    is not built; until it is, this returns the approved placeholder —
    `amount_at_risk`, so "higher amount at risk = higher priority" — via this one
    function. When Module 8 lands, only this body changes; every caller
    (`merge`, `human_queue`) already routes through it (D-098).
    """
    return Decimal(str(case.amount_at_risk or 0))


# --- cross-leg quiet period (Part A §5) ----------------------------------


def cross_leg_quiet_period_defer(
    session: Session,
    case: RevenueLeakCase,
    *,
    now: datetime,
    allowed_start: str,
    allowed_end: str,
    timing_offset_hours: float,
) -> datetime | None:
    """If a customer-contact `Action` from a **different leg** was executed for
    this counterparty at this merchant within the last `cross_leg_quiet_period_hours`,
    return the deferred fire time (`quiet_period_end + timing_offset`, pushed into
    `allowed_hours`); otherwise `None` (no quiet-period conflict).

    Within a single leg's own playbook the playbook's `timing_offset` governs and
    the coordinator adds nothing — hence `leg_type != case.leg_type`.
    """
    hours = get_policy().cross_leg_quiet_period_hours
    window_start = now - timedelta(hours=hours)
    scope = TenantScope(session, case.merchant_id)
    last_other_leg = session.scalar(
        scope.select(Action)
        .join(RevenueLeakCase, RevenueLeakCase.case_id == Action.primary_case_id)
        .where(RevenueLeakCase.merchant_id == case.merchant_id)
        .where(RevenueLeakCase.counterparty_id == case.counterparty_id)
        .where(RevenueLeakCase.leg_type != LegType(case.leg_type))
        .where(Action.action_type.in_(tuple(OUTREACH_ACTIONS)))
        .where(Action.executed_at.is_not(None))
        .where(Action.executed_at >= window_start)
        .with_only_columns(func.max(Action.executed_at))
    )
    if last_other_leg is None:
        return None
    if last_other_leg.tzinfo is None:
        from datetime import UTC

        last_other_leg = last_other_leg.replace(tzinfo=UTC)
    quiet_period_end = last_other_leg + timedelta(hours=hours)
    if quiet_period_end <= now:
        return None
    return timing.compute_fire_time(
        previous_completion=quiet_period_end,
        timing_offset_hours=timing_offset_hours,
        allowed_start=allowed_start,
        allowed_end=allowed_end,
        payday_adjustment=None,
    )


# --- open-conversation policy (Part A §5 / §3 active_wa_conversation) ----


def open_conversation_defer(
    session: Session,
    case: RevenueLeakCase,
    *,
    now: datetime,
    allowed_start: str,
    allowed_end: str,
) -> datetime | None:
    """If `Merchant_Counterparty.active_wa_conversation_expires_at > now`, return
    the deferred fire time (just past the conversation window, pushed into
    `allowed_hours`); otherwise `None`.

    A live 24h service-conversation window is not a template-sending opportunity —
    automated templates are suspended and the case is flagged for human pickup
    (the caller enqueues it; Q-F).
    """
    scope = TenantScope(session, case.merchant_id)
    mc = session.scalars(
        scope.select(MerchantCounterparty).where(
            MerchantCounterparty.counterparty_id == case.counterparty_id
        )
    ).first()
    if mc is None or mc.active_wa_conversation_expires_at is None:
        return None
    expires = mc.active_wa_conversation_expires_at
    if expires.tzinfo is None:
        from datetime import UTC

        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        return None
    return timing.compute_fire_time(
        previous_completion=expires,
        timing_offset_hours=0.0,
        allowed_start=allowed_start,
        allowed_end=allowed_end,
        payday_adjustment=None,
    )


# --- WhatsApp two-gate check (Blueprint §3 / §5.2 list 2 item 3) --------


def whatsapp_gate(session: Session, case: RevenueLeakCase) -> BlockReason | None:
    """Gate #1 (`Counterparty.whatsapp_opt_in`) AND gate #2 (an approved template
    of the right category for this leg). Returns the `BlockReason` on failure —
    `CONSENT_NOT_OBTAINED` (no opt-in) or `TEMPLATE_NOT_APPROVED` (no approved
    template) — or `None` when both pass.

    Reuses `torque.compliance.whatsapp.approved_template_exists` for gate #2
    (fail-closed on an exact `"APPROVED"`, INV-21) — the approval logic is not
    reimplemented here.
    """
    cp = session.get(Counterparty, case.counterparty_id)
    if cp is None or not cp.whatsapp_opt_in:
        return BlockReason.CONSENT_NOT_OBTAINED
    if not approved_template_exists(
        session,
        merchant_id=case.merchant_id,
        leg_type=LegType(case.leg_type),
        category=_OUTREACH_TEMPLATE_CATEGORY,
    ):
        return BlockReason.TEMPLATE_NOT_APPROVED
    return None


# --- merge candidate discovery (used by torque.coordination.merge) -----


def is_outreach_step(action_type: ActionType | str) -> bool:
    return ActionType(action_type) in OUTREACH_ACTIONS


#: Outcomes that count as an "unsuccessful attempt" toward `escalation_ceiling`
#: (Q-D): a guardrail block, a failed action, or a no-response outcome. A DEFER
#: never reaches an `Action` row, so a pure timing deferral is not counted;
#: `OUTREACH_COORDINATOR_DEFERRED` (which *does* write a blocked `Action`, Part A
#: §5) is counted — a case that can never get an outreach through legitimately
#: escalates to a human.
UNSUCCESSFUL_OUTCOMES: tuple[ActionOutcome, ...] = (
    ActionOutcome.BLOCKED_BY_GUARDRAIL,
    ActionOutcome.FAILED,
    ActionOutcome.NO_RESPONSE,
)


def unsuccessful_action_count(session: Session, *, merchant_id: str, run_id) -> int:
    """Count of `run_id`'s Actions whose outcome is in `UNSUCCESSFUL_OUTCOMES`
    (the escalation-ceiling tally, Blueprint §6.3 / Q-D). Tenant-scoped."""
    scope = TenantScope(session, merchant_id)
    return int(
        session.scalar(
            scope.select(Action)
            .where(Action.run_id == run_id)
            .where(Action.outcome.in_(UNSUCCESSFUL_OUTCOMES))
            .with_only_columns(func.count())
        )
        or 0
    )
