"""Deterministic `acc_demo` dataset — Blueprint §10.16.

`seed_demo(session)` builds a fixed, realistic spread of cases so the dashboard,
the top-at-risk list, the Agent Console queue and the exception list all open
with real content. Every dashboard number the UI shows is derived by Module 9
from these rows — nothing is hard-coded downstream.

Idempotent: a second call with `reset=False` is a no-op; `reset=True` wipes the
demo merchant's cases (raw SQL, because `CaseEvent` is append-only and cannot be
ORM-deleted) and rebuilds.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.enums import (
    ActionOutcome,
    ActionType,
    Actor,
    BlockReason,
    CaseEventType,
    CaseStatus,
    LegType,
    RecoveryType,
)
from torque.events import Attribution, append_case_event, write_action_and_event
from torque.models import (
    Action,
    B2BInvoice,
    Counterparty,
    Event,
    Merchant,
    MerchantCounterparty,
    RevenueLeakCase,
)
from torque.models.guards import module7_writer
from torque.policy.catalog import seed_catalog
from torque.scoring.score import score_case
from torque.state_machine import sync_control_group, transition_case

DEMO_MERCHANT_ID = "acc_demo"
#: A second merchant that is actively treating two of `acc_demo`'s held-out
#: control counterparties in the same window — so the dashboard's SUTVA-adjusted
#: lift (Module 9b / Blueprint §6) is a live, non-zero number rather than always
#: equal to the headline. Built and wiped alongside `acc_demo`.
DEMO_UPSTREAM_MERCHANT_ID = "acc_demo_up"
DEMO_MERCHANT_IDS = (DEMO_MERCHANT_ID, DEMO_UPSTREAM_MERCHANT_ID)
#: Fixed clock so `days_since_failure` buckets — and therefore every recovery
#: score — are identical on every seed.
DEMO_NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

_SUB_MANDATES = ("CARD", "UPI_AUTOPAY", "NACH")


@dataclass
class _Ctx:
    session: Session
    scope: TenantScope
    now: datetime
    seq: int = 0
    cases: list[RevenueLeakCase] = field(default_factory=list)

    def event_id(self) -> uuid.UUID:
        self.seq += 1
        ev = Event(
            merchant_id=DEMO_MERCHANT_ID,
            type="demo.seed",
            idempotency_key=f"demo_seed_{self.seq}_{uuid.uuid4().hex[:8]}",
            raw_payload={"demo": True},
        )
        self.session.add(ev)
        self.session.flush()
        return ev.event_id


# --- primitives ------------------------------------------------------


def _counterparty(ctx: _Ctx, name: str, phone: str, *, opt_in: bool = True,
                  promise_rate: float | None = None,
                  in_control: bool = False) -> Counterparty:
    cp = Counterparty(
        name=name, phone=phone, email=f"{phone.strip('+')}@demo.test",
        payment_failure_nudge_consent=True, whatsapp_opt_in=opt_in,
    )
    ctx.session.add(cp)
    ctx.session.flush()
    mc = MerchantCounterparty(
        merchant_id=DEMO_MERCHANT_ID, counterparty_id=cp.counterparty_id,
        promise_keeping_rate=promise_rate,
    )
    ctx.session.add(mc)
    ctx.session.flush()
    # Incrementality cohort (Blueprint §6) — assigned once, via the sanctioned
    # `assign_cohort`; `cohort_assigned_at` pinned to the fixed demo clock so the
    # rebuild is byte-identical. `control` = held out (no outreach).
    mc.assign_cohort(in_control)
    mc.cohort_assigned_at = ctx.now
    ctx.session.flush()
    return cp


def _new_case(
    ctx: _Ctx, *, leg: LegType, cp: Counterparty, amount, context: dict,
    opened_ago_hours: float,
) -> RevenueLeakCase:
    case = RevenueLeakCase(
        leg_type=leg,
        source_event_id=ctx.event_id(),
        counterparty_id=cp.counterparty_id,
        amount_at_risk=Decimal(str(amount)),
        status=CaseStatus.DETECTED,
        context=context,
        opened_at=ctx.now - timedelta(hours=opened_ago_hours),
    )
    ctx.scope.add(case)
    ctx.session.flush()
    sync_control_group(ctx.session, case)
    ctx.cases.append(case)
    return case


def _ev(ctx: _Ctx, case, etype: CaseEventType, payload: dict, *, reasoning: str,
        actor: Actor = Actor.AGENT, at_ago_hours: float = 0.0) -> None:
    row = append_case_event(
        ctx.session, case_id=case.case_id, event_type=etype, payload=payload,
        actor=actor, reasoning=reasoning, counterparty_id=case.counterparty_id,
    )
    row.timestamp = ctx.now - timedelta(hours=at_ago_hours)


def _advance(ctx: _Ctx, case, target: CaseStatus, *, trigger: str,
             reasoning: str, actor: Actor = Actor.AGENT) -> None:
    transition_case(ctx.session, case, target, trigger=trigger, actor=actor,
                    reasoning=reasoning)
    ctx.session.flush()


def _diagnose(ctx: _Ctx, case, *, root_cause: str, confidence: float,
              at_ago_hours: float) -> None:
    case.root_cause_code = root_cause
    case.diagnosis_confidence = confidence
    _ev(ctx, case, CaseEventType.DIAGNOSIS_COMPLETED,
        {"root_cause_code": root_cause, "diagnosis_confidence": confidence,
         "network_directive": None},
        reasoning=f"Diagnosis: {root_cause.replace('_', ' ').lower()} "
                  f"(confidence {confidence:.2f})",
        at_ago_hours=at_ago_hours)
    ctx.session.flush()


def _action(ctx: _Ctx, case, atype: ActionType, outcome: ActionOutcome, *,
            channel: str | None, block_reason: BlockReason | None = None,
            cost=None) -> Action:
    blocked = outcome is ActionOutcome.BLOCKED_BY_GUARDRAIL
    action = Action(
        merchant_id=DEMO_MERCHANT_ID, primary_case_id=case.case_id, run_id=None,
        action_type=atype, channel=channel,
        executed_at=None if blocked else ctx.now - timedelta(hours=1),
        outcome=outcome, block_reason=block_reason,
        cost=Decimal(str(cost)) if cost is not None else None,
    )
    write_action_and_event(
        ctx.session, action=action, actor=Actor.AGENT,
        attributions=[Attribution(case_id=case.case_id, is_primary=True,
                                  credit_weight=Decimal("1.00000"))],
    )
    return action


def _recover(ctx: _Ctx, case, amount, rtype: RecoveryType, *,
             at_ago_hours: float = 0.25) -> None:
    with module7_writer(ctx.session):
        case.recovery_type = rtype
        case.recovered_amount = Decimal(str(amount))
        case.closed_at = ctx.now - timedelta(hours=at_ago_hours)
        _ev(ctx, case, CaseEventType.PAYMENT_RECONCILED,
            {"recovered_amount": Decimal(str(amount)), "recovery_type": rtype},
            reasoning=f"Payment reconciled — ₹{Decimal(str(amount)):,.0f} recovered "
                      f"({rtype.value})",
            actor=Actor.SYSTEM, at_ago_hours=at_ago_hours)
        ctx.session.flush()


def _b2b_invoices(ctx: _Ctx, case, originals: list, *, outstanding: list | None = None):
    outs = outstanding or originals
    for i, (orig, out) in enumerate(zip(originals, outs, strict=True)):
        ctx.session.add(B2BInvoice(
            merchant_id=DEMO_MERCHANT_ID, case_id=case.case_id,
            counterparty_id=case.counterparty_id,
            due_date=(ctx.now - timedelta(days=40 - i * 5)).date(),
            days_overdue=40 - i * 5,
            original_amount=Decimal(str(orig)),
            outstanding_amount=Decimal(str(out)),
        ))
    ctx.session.flush()
    case.amount_at_risk = sum((Decimal(str(o)) for o in outs), Decimal("0"))
    ctx.session.flush()


# --- context builders ---------------------------------------------


def _pd_ctx(decline: str = "GATEWAY_ERROR") -> dict:
    return {"gateway": "razorpay", "decline_code": decline, "retry_count": 1}


def _sub_ctx(mandate: str, sub_id: str) -> dict:
    return {"mandate_id": f"mand_{sub_id}", "mandate_type": mandate,
            "billing_cycle": "monthly", "subscription_id": sub_id}


def _co_ctx(cart: str, value) -> dict:
    return {"cart_id": cart, "cart_value": str(value), "drop_stage": "vpa_entry",
            "payment_method_attempted": "UPI_COLLECT"}


# --- archetypes --------------------------------------------------


def _recovered_case(ctx: _Ctx, *, leg, cp, amount, context, root_cause,
                    confidence, rtype=RecoveryType.AGENT_ASSISTED,
                    action_type=ActionType.RETRY_PAYMENT, channel=None,
                    opened_ago=30.0) -> RevenueLeakCase:
    case = _new_case(ctx, leg=leg, cp=cp, amount=amount, context=context,
                     opened_ago_hours=opened_ago)
    _advance(ctx, case, CaseStatus.DIAGNOSING, trigger="diagnosis_started",
             reasoning="Diagnosis started")
    _diagnose(ctx, case, root_cause=root_cause, confidence=confidence,
              at_ago_hours=opened_ago - 0.5)
    _advance(ctx, case, CaseStatus.PLAYBOOK_ACTIVE, trigger="diagnosis_confident",
             reasoning="Recovery playbook selected")
    _action(ctx, case, action_type, ActionOutcome.SUCCESS, channel=channel)
    _advance(ctx, case, CaseStatus.RECOVERED, trigger="payment_reconciled",
             reasoning="Case recovered", actor=Actor.SYSTEM)
    _recover(ctx, case, amount, rtype)
    return case


def _self_paid_case(ctx: _Ctx, *, cp, amount) -> RevenueLeakCase:
    case = _new_case(ctx, leg=LegType.PAYMENT_DEGRADATION, cp=cp, amount=amount,
                     context=_pd_ctx("SOFT_DECLINE"), opened_ago_hours=20.0)
    _advance(ctx, case, CaseStatus.DIAGNOSING, trigger="diagnosis_started",
             reasoning="Diagnosis started")
    _advance(ctx, case, CaseStatus.CANCELLED, trigger="customer_self_paid",
             reasoning="Customer self-paid before Torque acted", actor=Actor.SYSTEM)
    _recover(ctx, case, amount, RecoveryType.SELF_RECOVERED)
    return case


def _blocked_case(ctx: _Ctx, *, leg, cp, amount, context, root_cause,
                  block_reason: BlockReason, action_type=ActionType.RETRY_PAYMENT,
                  channel=None) -> RevenueLeakCase:
    case = _new_case(ctx, leg=leg, cp=cp, amount=amount, context=context,
                     opened_ago_hours=6.0)
    _advance(ctx, case, CaseStatus.DIAGNOSING, trigger="diagnosis_started",
             reasoning="Diagnosis started")
    _diagnose(ctx, case, root_cause=root_cause, confidence=0.82, at_ago_hours=5.5)
    _advance(ctx, case, CaseStatus.PLAYBOOK_ACTIVE, trigger="diagnosis_confident",
             reasoning="Recovery playbook selected")
    _action(ctx, case, action_type, ActionOutcome.BLOCKED_BY_GUARDRAIL,
            channel=channel, block_reason=block_reason)
    return case


def _escalated_case(ctx: _Ctx, *, leg, cp, amount, context, root_cause, confidence,
                    queue_reason: str, opened_ago=8.0,
                    b2b_originals: list | None = None) -> RevenueLeakCase:
    from torque.coordination import human_queue

    case = _new_case(ctx, leg=leg, cp=cp, amount=amount, context=context,
                     opened_ago_hours=opened_ago)
    if b2b_originals:
        _b2b_invoices(ctx, case, b2b_originals)  # sets amount_at_risk before scoring
    _advance(ctx, case, CaseStatus.DIAGNOSING, trigger="diagnosis_started",
             reasoning="Diagnosis started")
    _diagnose(ctx, case, root_cause=root_cause, confidence=confidence,
              at_ago_hours=opened_ago - 0.3)
    _advance(ctx, case, CaseStatus.ESCALATED_TO_HUMAN, trigger="diagnosis_low_confidence",
             reasoning="Routed to a human agent")
    score_case(ctx.session, case, now=ctx.now)  # so the queue priority is meaningful
    human_queue.enqueue(ctx.session, case=case, reason=queue_reason, now=ctx.now)
    ctx.session.flush()
    return case


def _open_case(ctx: _Ctx, *, leg, cp, amount, context, root_cause, confidence,
               opened_ago: float) -> RevenueLeakCase:
    case = _new_case(ctx, leg=leg, cp=cp, amount=amount, context=context,
                     opened_ago_hours=opened_ago)
    _advance(ctx, case, CaseStatus.DIAGNOSING, trigger="diagnosis_started",
             reasoning="Diagnosis started")
    _diagnose(ctx, case, root_cause=root_cause, confidence=confidence,
              at_ago_hours=opened_ago - 0.2)
    _advance(ctx, case, CaseStatus.PLAYBOOK_ACTIVE, trigger="diagnosis_confident",
             reasoning="Recovery playbook active")
    _action(ctx, case, ActionType.SEND_WHATSAPP, ActionOutcome.NO_RESPONSE,
            channel="whatsapp", cost="0.885")
    return case


# --- entrypoint -------------------------------------------------


_CASE_SUBQ = "(SELECT case_id FROM revenue_leak_case WHERE merchant_id = :m)"
_WIPE_STMTS = (
    f"DELETE FROM case_event WHERE case_id IN {_CASE_SUBQ}",
    f"DELETE FROM action_case WHERE case_id IN {_CASE_SUBQ}",
    "DELETE FROM action WHERE merchant_id = :m",
    "DELETE FROM human_queue WHERE merchant_id = :m",
    "DELETE FROM b2b_invoice WHERE merchant_id = :m",
    "DELETE FROM payment_link WHERE merchant_id = :m",
    "DELETE FROM promise_to_pay WHERE merchant_id = :m",
    "DELETE FROM card_retry_budget WHERE merchant_id = :m",
    "DELETE FROM upi_retry_budget WHERE merchant_id = :m",
    "DELETE FROM nach_retry_policy WHERE merchant_id = :m",
    "DELETE FROM revenue_leak_case WHERE merchant_id = :m",
    "DELETE FROM event WHERE merchant_id = :m",
)


def _wipe(session: Session) -> None:
    """Delete the demo merchants' data (`acc_demo` + the `acc_demo_up`
    contamination fixture). `case_event` is protected by a Postgres
    `BEFORE DELETE` trigger (append-only, §2.3) — a demo *reset* explicitly
    disables it for the wipe and re-enables it in the same transaction (needs
    table ownership; a rollback reverts both). Strictly scoped to the demo
    merchant ids."""
    session.execute(
        text("ALTER TABLE case_event DISABLE TRIGGER case_event_no_mutate")
    )
    try:
        for m in DEMO_MERCHANT_IDS:
            for stmt in _WIPE_STMTS:
                session.execute(text(stmt), {"m": m})
    finally:
        session.execute(
            text("ALTER TABLE case_event ENABLE TRIGGER case_event_no_mutate")
        )
    session.flush()


def seed_demo(
    session: Session, *, now: datetime | None = None, reset: bool = False
) -> dict:
    """Build (or, with `reset`, rebuild) the `acc_demo` dataset. Returns a small
    summary. The caller owns the transaction."""
    now = now or DEMO_NOW
    seed_catalog(session)

    merchant = session.get(Merchant, DEMO_MERCHANT_ID)
    if merchant is None:
        merchant = Merchant(
            merchant_id=DEMO_MERCHANT_ID, business_type="D2C SaaS", tier="Metro",
            channels_enabled=["whatsapp", "email", "sms"],
            risk_appetite_config={"payday_cycle_override_enabled": False},
        )
        session.add(merchant)
        session.flush()

    existing = session.scalar(
        select(RevenueLeakCase.case_id)
        .where(RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID)
        .limit(1)
    )
    if existing is not None:
        if not reset:
            return _summary(session, seeded=False)
        _wipe(session)

    ctx = _Ctx(session=session, scope=TenantScope(session, DEMO_MERCHANT_ID), now=now)

    # --- recovered (Torque-credited) across legs ---
    _recovered_case(
        ctx, leg=LegType.SUBSCRIPTION_FAILURE,
        cp=_counterparty(ctx, "Aarav Mehta", "+919810010001", promise_rate=0.9),
        amount="12400.00", context=_sub_ctx("CARD", "sub_demo_01"),
        root_cause="NSF_SOFT_DECLINE", confidence=0.87,
        action_type=ActionType.RETRY_PAYMENT, opened_ago=30.0,
    )
    _recovered_case(
        ctx, leg=LegType.PAYMENT_DEGRADATION,
        cp=_counterparty(ctx, "Priya Nair", "+919810010002", promise_rate=0.75),
        amount="6800.00", context=_pd_ctx("ISSUER_TIMEOUT"),
        root_cause="GATEWAY_TIMEOUT", confidence=0.9,
        action_type=ActionType.RETRY_PAYMENT, opened_ago=54.0,
    )
    _recovered_case(
        ctx, leg=LegType.CHECKOUT_ABANDONMENT,
        cp=_counterparty(ctx, "Rohan Gupta", "+919810010003"),
        amount="3100.00", context=_co_ctx("cart_demo_01", "3100.00"),
        root_cause="UPI_COLLECT_FRICTION", confidence=0.78,
        action_type=ActionType.SEND_WHATSAPP, channel="whatsapp", opened_ago=12.0,
    )
    _recovered_case(
        ctx, leg=LegType.PAYMENT_DEGRADATION,
        cp=_counterparty(ctx, "Ananya Rao", "+919810010004", promise_rate=0.6),
        amount="9900.00", context=_pd_ctx("SOFT_DECLINE"),
        root_cause="ISSUER_SOFT_DECLINE_NSF", confidence=0.85,
        action_type=ActionType.RETRY_PAYMENT, opened_ago=6.0,
    )

    # B2B recovered fully
    b2b_rec = _new_case(
        ctx, leg=LegType.B2B_RECEIVABLE,
        cp=_counterparty(ctx, "Sunrise Traders Pvt Ltd", "+919810020001", promise_rate=0.8),
        amount="0.00", context={}, opened_ago_hours=40.0,
    )
    _b2b_invoices(ctx, b2b_rec, ["18000.00"], outstanding=["18000.00"])
    _advance(ctx, b2b_rec, CaseStatus.DIAGNOSING, trigger="diagnosis_started",
             reasoning="Diagnosis started")
    _diagnose(ctx, b2b_rec, root_cause="LIQUIDITY_DELAY_LOW_RISK", confidence=0.8,
              at_ago_hours=39.0)
    _advance(ctx, b2b_rec, CaseStatus.PLAYBOOK_ACTIVE, trigger="diagnosis_confident",
             reasoning="B2B dunning playbook active")
    _action(ctx, b2b_rec, ActionType.SEND_EMAIL, ActionOutcome.SUCCESS, channel="email",
            cost="0.01")
    for inv in ctx.session.scalars(
        select(B2BInvoice).where(B2BInvoice.case_id == b2b_rec.case_id)
    ).all():
        inv.outstanding_amount = Decimal("0.00")
    ctx.session.flush()
    _advance(ctx, b2b_rec, CaseStatus.RECOVERED, trigger="payment_reconciled",
             reasoning="Invoice settled", actor=Actor.SYSTEM)
    _recover(ctx, b2b_rec, "18000.00", RecoveryType.AGENT_ASSISTED)

    # --- self-recovered --- (held-out CONTROL; also treated upstream → contaminated)
    cp_vikram = _counterparty(ctx, "Vikram Singh", "+919810010005", in_control=True)
    _self_paid_case(ctx, cp=cp_vikram, amount="4500.00")

    # --- B2B partially recovered (still open) ---
    b2b_partial = _new_case(
        ctx, leg=LegType.B2B_RECEIVABLE,
        cp=_counterparty(ctx, "Delta Logistics LLP", "+919810020002", promise_rate=0.45),
        amount="0.00", context={}, opened_ago_hours=70.0,
    )
    _b2b_invoices(ctx, b2b_partial, ["15000.00", "9000.00"],
                  outstanding=["0.00", "9000.00"])
    _advance(ctx, b2b_partial, CaseStatus.DIAGNOSING, trigger="diagnosis_started",
             reasoning="Diagnosis started")
    _diagnose(ctx, b2b_partial, root_cause="LIQUIDITY_DELAY_HIGH_RISK", confidence=0.7,
              at_ago_hours=69.0)
    _advance(ctx, b2b_partial, CaseStatus.PLAYBOOK_ACTIVE, trigger="diagnosis_confident",
             reasoning="B2B dunning playbook active")
    _advance(ctx, b2b_partial, CaseStatus.PARTIALLY_RECOVERED, trigger="payment_reconciled",
             reasoning="Partial payment received — one invoice cleared", actor=Actor.SYSTEM)
    with module7_writer(ctx.session):
        b2b_partial.recovery_type = RecoveryType.AGENT_ASSISTED
        b2b_partial.recovered_amount = Decimal("15000.00")
        _ev(ctx, b2b_partial, CaseEventType.PAYMENT_RECONCILED,
            {"recovered_amount": Decimal("15000.00"), "recovery_type": RecoveryType.AGENT_ASSISTED},
            reasoning="₹15,000 of ₹24,000 recovered; ₹9,000 still outstanding",
            actor=Actor.SYSTEM, at_ago_hours=2.0)
        ctx.session.flush()

    # --- blocked (compliance restraint) ---
    _blocked_case(
        ctx, leg=LegType.PAYMENT_DEGRADATION,
        cp=_counterparty(ctx, "Kabir Shah", "+919810010006"),
        amount="7300.00", context=_pd_ctx("MAC_03"),
        root_cause="ISSUER_HARD_DECLINE_FRAUD_SUSPECTED",
        block_reason=BlockReason.NETWORK_HARD_STOP,
        action_type=ActionType.RETRY_PAYMENT,
    )
    _blocked_case(
        ctx, leg=LegType.CHECKOUT_ABANDONMENT,
        cp=_counterparty(ctx, "Meera Iyer", "+919810010007", opt_in=False),
        amount="2200.00", context=_co_ctx("cart_demo_02", "2200.00"),
        root_cause="NO_PAYMENT_METHOD_ATTEMPTED",
        block_reason=BlockReason.CONSENT_NOT_OBTAINED,
        action_type=ActionType.SEND_WHATSAPP, channel="whatsapp",
    )
    # --- deferred ---
    _blocked_case(
        ctx, leg=LegType.PAYMENT_DEGRADATION,
        cp=_counterparty(ctx, "Ishaan Verma", "+919810010008"),
        amount="5400.00", context=_pd_ctx("SOFT_DECLINE"),
        root_cause="ISSUER_SOFT_DECLINE_OTHER",
        block_reason=BlockReason.OUTREACH_COORDINATOR_DEFERRED,
        action_type=ActionType.SEND_WHATSAPP, channel="whatsapp",
    )

    # --- escalated to a human ---
    _escalated_case(
        ctx, leg=LegType.B2B_RECEIVABLE,
        cp=_counterparty(ctx, "Orion Enterprises", "+919810020003", promise_rate=0.3),
        amount="0.00", context={}, root_cause="DISPUTE_SUSPECTED", confidence=0.4,
        queue_reason="LOW_CONFIDENCE_DIAGNOSIS", opened_ago=10.0,
        b2b_originals=["26000.00"],
    )
    _escalated_case(
        ctx, leg=LegType.SUBSCRIPTION_FAILURE,
        cp=_counterparty(ctx, "Tara Menon", "+919810010009", promise_rate=0.5),
        amount="18900.00", context=_sub_ctx("UPI_AUTOPAY", "sub_demo_09"),
        root_cause="UNKNOWN_SUBSCRIPTION_FAILURE", confidence=0.45,
        queue_reason="ESCALATION_CEILING", opened_ago=16.0,
    )

    # --- exhausted --- (held-out CONTROL; also treated upstream → contaminated)
    cp_nikhil = _counterparty(ctx, "Nikhil Joshi", "+919810010010", in_control=True)
    exhausted = _new_case(
        ctx, leg=LegType.CHECKOUT_ABANDONMENT, cp=cp_nikhil,
        amount="1500.00", context=_co_ctx("cart_demo_03", "1500.00"),
        opened_ago_hours=120.0,
    )
    _advance(ctx, exhausted, CaseStatus.DIAGNOSING, trigger="diagnosis_started",
             reasoning="Diagnosis started")
    _diagnose(ctx, exhausted, root_cause="UNKNOWN_ABANDONMENT", confidence=0.7,
              at_ago_hours=119.0)
    _advance(ctx, exhausted, CaseStatus.PLAYBOOK_ACTIVE, trigger="diagnosis_confident",
             reasoning="Cart-nudge playbook active")
    _action(ctx, exhausted, ActionType.SEND_WHATSAPP, ActionOutcome.NO_RESPONSE,
            channel="whatsapp", cost="0.885")
    _advance(ctx, exhausted, CaseStatus.EXHAUSTED, trigger="stopping_rule",
             reasoning="Playbook exhausted its attempts with no recovery",
             actor=Actor.SYSTEM)

    # --- open, unresolved, freshly scored (drive "top at risk") ---
    _open_case(
        ctx, leg=LegType.SUBSCRIPTION_FAILURE,
        cp=_counterparty(ctx, "Diya Kapoor", "+919810010011", promise_rate=0.7),
        amount="24000.00", context=_sub_ctx("CARD", "sub_demo_11"),
        root_cause="NSF_SOFT_DECLINE", confidence=0.86, opened_ago=20.0,
    )
    _open_case(
        ctx, leg=LegType.PAYMENT_DEGRADATION,
        cp=_counterparty(ctx, "Arjun Pillai", "+919810010012"),
        amount="15600.00", context=_pd_ctx("SOFT_DECLINE"),
        root_cause="ISSUER_SOFT_DECLINE_NSF", confidence=0.83, opened_ago=3.0,
    )
    # held-out CONTROL, clean (no upstream treatment) → retained by SUTVA
    cp_sara = _counterparty(ctx, "Sara Khan", "+919810010013", promise_rate=0.4,
                            in_control=True)
    _open_case(
        ctx, leg=LegType.SUBSCRIPTION_FAILURE, cp=cp_sara,
        amount="8200.00", context=_sub_ctx("NACH", "sub_demo_13"),
        root_cause="NSF_SOFT_DECLINE", confidence=0.8, opened_ago=90.0,
    )

    # --- score every non-terminal case (Module 8) ---
    for case in session.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID)
    ).all():
        score_case(session, case, now=now)
    session.flush()

    # --- Module 9b: cross-merchant SUTVA contamination fixture ---
    _seed_upstream_contamination(session, contaminated=(cp_vikram, cp_nikhil), now=now)

    return _summary(session, seeded=True)


def _seed_upstream_contamination(
    session: Session, *, contaminated: tuple[Counterparty, ...], now: datetime
) -> None:
    """A second merchant (`acc_demo_up`) actively treating each counterparty in
    `contaminated` — cohort `treatment`, a case opened in the same window. That
    makes them Blueprint §6 contaminated control units for `acc_demo`, so the
    dashboard's SUTVA-adjusted lift differs from the headline. Only the
    counterparty overlap matters; these rows are otherwise minimal."""
    up = session.get(Merchant, DEMO_UPSTREAM_MERCHANT_ID)
    if up is None:
        up = Merchant(
            merchant_id=DEMO_UPSTREAM_MERCHANT_ID, business_type="B2B Marketplace",
            tier="Metro", channels_enabled=["email"], risk_appetite_config={},
        )
        session.add(up)
        session.flush()
    scope = TenantScope(session, DEMO_UPSTREAM_MERCHANT_ID)
    for cp in contaminated:
        mc = MerchantCounterparty(
            merchant_id=DEMO_UPSTREAM_MERCHANT_ID, counterparty_id=cp.counterparty_id,
        )
        session.add(mc)
        session.flush()
        mc.assign_cohort(False)  # treatment at the other merchant
        mc.cohort_assigned_at = now
        ev = Event(
            merchant_id=DEMO_UPSTREAM_MERCHANT_ID, type="demo.seed",
            idempotency_key=f"demo_up_{cp.counterparty_id.hex[:16]}",
            raw_payload={"demo": True},
        )
        session.add(ev)
        session.flush()
        case = RevenueLeakCase(
            leg_type=LegType.B2B_RECEIVABLE, source_event_id=ev.event_id,
            counterparty_id=cp.counterparty_id, amount_at_risk=Decimal("5000.00"),
            status=CaseStatus.PLAYBOOK_ACTIVE, context={},
            opened_at=now - timedelta(hours=18),
        )
        scope.add(case)
        session.flush()
        sync_control_group(session, case)
    session.flush()


def _summary(session: Session, *, seeded: bool) -> dict:
    n = session.scalar(
        select(func.count())
        .select_from(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID)
    )
    return {"merchant_id": DEMO_MERCHANT_ID, "seeded": seeded, "case_count": int(n or 0)}
