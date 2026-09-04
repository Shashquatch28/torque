"""One-click synthetic demo scenarios — Blueprint §10.10 / §5.4 Decision K.

`inject_scenario(session, key)` composes the **existing** ingestion / compliance
code into a single visible event on the demo merchant:

* `payment_failure` / `checkout_abandonment` — run the real Module 2 ingestion
  function (`create_or_attach_case` / `create_checkout_case`) so a genuine
  `DETECTED` case enters the pipeline;
* `hard_stop_mac` / `upi_retry_cap` / `nach_ceiling` — the Decision-K restraint
  scenarios: create the case, seed the blocking budget row, **assert the real
  compliance predicate refuses the retry**, and record the
  `BLOCKED_BY_GUARDRAIL` action so it appears in the exception list and the
  case timeline;
* `cross_leg_merge` / `b2b_invoice_bundle` (Module 12a / B1) — the real §2.4
  bidirectional cross-leg Merge (`ingestion.cases.create_or_attach_case` +
  `ingestion.checkout.create_checkout_case`, via `ingestion.dedup`) and the real
  §3 B2B grouping rule (`ingestion.b2b.ingest_invoice`), for the **same**
  counterparty, so the "one case object, one ledger" differentiator is a live
  click, not just the static seed.

No parallel event-generation mechanism is invented.

**`dispatch=True`** (Module 12a / D-137) additionally wires
`torque.ingestion.tasks.dispatch_diagnosis` into the real ingestion calls above,
so the resulting case is picked up by the same autonomous
ingestion→diagnosis→policy-activation→execution chain a real webhook would
trigger — asynchronously, via the real Celery broker; this function itself
still returns immediately with the case as ingestion left it (never blocks on
the dispatched work). Defaults to `False` so every existing direct caller (the
whole Module 10 demo test suite) is unaffected; `torque.api.demo` is the one
caller that opts in, matching how `api/webhooks.py` already dispatches for a
real Razorpay webhook.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torque.compliance import (
    card_retry_within_budget,
    nach_retry_eligible,
    upi_attempt_gate_open,
)
from torque.db.scoped import TenantScope
from torque.demo.seed import DEMO_MERCHANT_ID
from torque.enums import (
    ActionOutcome,
    ActionType,
    Actor,
    BlockReason,
    CaseEventType,
    CaseStatus,
    ClearingCycleStatus,
    HardStopReason,
)
from torque.events import Attribution, append_case_event, write_action_and_event
from torque.ingestion.b2b import ingest_invoice
from torque.ingestion.cases import create_or_attach_case
from torque.ingestion.checkout import create_checkout_case
from torque.ingestion.subscription import create_subscription_case
from torque.ingestion.tasks import dispatch_diagnosis
from torque.models import (
    Action,
    B2BInvoice,
    CardRetryBudget,
    Event,
    NACHRetryPolicy,
    RevenueLeakCase,
    UPIRetryBudget,
)
from torque.scoring.score import score_case
from torque.state_machine import transition_case

DEMO_SCENARIOS: list[dict] = [
    {"key": "payment_failure", "label": "Payment failure", "kind": "act",
     "description": "A fresh degraded payment enters the pipeline (Leg 1)."},
    {"key": "checkout_abandonment", "label": "Checkout abandonment", "kind": "act",
     "description": "A shopper drops at VPA entry — the synthetic injector (Leg 2)."},
    {"key": "hard_stop_mac", "label": "Network hard-stop (MAC 03)", "kind": "restraint",
     "description": "Tier-1 do-not-retry directive — Torque refuses the retry."},
    {"key": "upi_retry_cap", "label": "UPI AutoPay retry cap", "kind": "restraint",
     "description": "The mandate has used its 3 NPCI retries — Torque stops."},
    {"key": "nach_ceiling", "label": "NACH representment ceiling", "kind": "restraint",
     "description": "The self-imposed 3/cycle NACH ceiling is reached — Torque stops."},
    {"key": "cross_leg_merge", "label": "Cross-leg merge", "kind": "act",
     "description": "The same customer abandons checkout, then their retry fails "
                    "— one ledger, not two cases (Leg 1 <-> Leg 2)."},
    {"key": "b2b_invoice_bundle", "label": "B2B invoice bundle", "kind": "act",
     "description": "A second overdue invoice for the same counterparty bundles "
                    "into their one open receivable case (Leg 4)."},
]
_KEYS = {s["key"] for s in DEMO_SCENARIOS}

_seq = {"n": 1000}


def _next(prefix: str) -> str:
    _seq["n"] += 1
    return f"{prefix}_{_seq['n']}_{uuid.uuid4().hex[:6]}"


def _contact() -> str:
    _seq["n"] += 1
    return f"+9198{_seq['n']:08d}"[:14]


def _paise(rupees: str | Decimal) -> int:
    return int(Decimal(str(rupees)) * 100)


def _event(session: Session, *, etype: str, payload: dict) -> Event:
    ev = Event(
        merchant_id=DEMO_MERCHANT_ID, type=etype,
        idempotency_key=_next("demo_evt"), raw_payload=payload,
    )
    session.add(ev)
    session.flush()
    return ev


def _payment_payload(*, amount, contact, method="card", token=None,
                     error_code="SOFT_DECLINE", order_id=None) -> dict:
    entity = {
        "id": _next("pay"), "amount": _paise(amount), "currency": "INR",
        "method": method, "contact": contact,
        "email": f"{contact.strip('+')}@demo.test", "error_code": error_code,
        "order_id": order_id or _next("order"),
    }
    if token:
        entity["token_id"] = token
    return {"entity": "event", "event": "payment.failed",
            "payload": {"payment": {"entity": entity}}, "created_at": 1_760_000_000}


def _checkout_payload(*, value, contact, cart_id=None) -> dict:
    return {"event": "checkout.abandoned", "created_at": 1_760_000_000,
            "payload": {"checkout": {"entity": {
                "cart_id": cart_id or _next("cart"), "cart_value": _paise(value),
                "drop_stage": "vpa_entry", "payment_method_attempted": "UPI_COLLECT",
                "contact": contact, "email": f"{contact.strip('+')}@demo.test",
            }}}}


def _invoice_payload(*, original, contact, outstanding=None, terms="NET30") -> dict:
    original_paise = _paise(original)
    entity = {
        "id": _next("inv"), "amount": original_paise, "currency": "INR",
        "amount_paid": 0,
        "amount_due": _paise(outstanding) if outstanding is not None else original_paise,
        "expire_by": 1_760_000_000, "terms": terms,
        "customer_details": {"contact": contact, "email": f"{contact.strip('+')}@demo.test"},
        "gst": {"gstin": "27AAAAA0000A1Z5"},
    }
    return {"entity": "event", "event": "invoice.overdue", "created_at": 1_760_000_000,
            "payload": {"invoice": {"entity": entity}}}


def _sub_payload(*, amount, contact, method) -> dict:
    return {"entity": "event", "event": "subscription.charged.failed",
            "created_at": 1_760_000_000,
            "payload": {
                "payment": {"entity": {
                    "id": _next("pay"), "amount": _paise(amount), "currency": "INR",
                    "method": method, "contact": contact,
                    "email": f"{contact.strip('+')}@demo.test", "error_code": "SOFT_DECLINE",
                }},
                "subscription": {"entity": {
                    "id": _next("sub"), "paid_count": 3, "status": "active",
                }},
            }}


def _case_for_event(session: Session, event_id: uuid.UUID) -> RevenueLeakCase:
    case = session.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.source_event_id == event_id)
    ).first()
    if case is None:  # pragma: no cover
        raise RuntimeError(f"demo scenario produced no case for event {event_id}")
    return case


def _diagnose_to_playbook(session: Session, case: RevenueLeakCase, *, root_cause: str) -> None:
    transition_case(session, case, CaseStatus.DIAGNOSING, trigger="diagnosis_started",
                    actor=Actor.AGENT, reasoning="Diagnosis started")
    case.root_cause_code = root_cause
    case.diagnosis_confidence = 0.85
    append_case_event(
        session, case_id=case.case_id, event_type=CaseEventType.DIAGNOSIS_COMPLETED,
        payload={"root_cause_code": root_cause, "diagnosis_confidence": 0.85,
                 "network_directive": None},
        actor=Actor.AGENT, reasoning=f"Diagnosed: {root_cause}",
        counterparty_id=case.counterparty_id,
    )
    transition_case(session, case, CaseStatus.PLAYBOOK_ACTIVE, trigger="diagnosis_confident",
                    actor=Actor.AGENT, reasoning="Recovery playbook active")
    session.flush()


def _blocked_action(session: Session, case: RevenueLeakCase, *,
                    block_reason: BlockReason) -> None:
    action = Action(
        merchant_id=DEMO_MERCHANT_ID, primary_case_id=case.case_id, run_id=None,
        action_type=ActionType.RETRY_PAYMENT, channel=None, executed_at=None,
        outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL, block_reason=block_reason, cost=None,
    )
    write_action_and_event(
        session, action=action, actor=Actor.AGENT,
        reasoning=f"Guardrail refused the retry: {block_reason.value}",
        attributions=[Attribution(case_id=case.case_id, is_primary=True,
                                  credit_weight=Decimal("1.00000"))],
    )


def inject_scenario(
    session: Session, key: str, *, now: datetime | None = None, dispatch: bool = False
) -> dict:
    """Run one demo scenario against `acc_demo`. The caller owns the transaction.

    `dispatch=True` (Module 12a) wires `torque.ingestion.tasks.dispatch_diagnosis`
    into the real ingestion calls below — the same dispatch a real webhook makes
    (`api/webhooks.py`), fired from inside this still-open transaction, exactly
    like that existing caller. Defaults to `False`: every direct call (the whole
    Module 10 demo test suite) is unaffected; `torque.api.demo` opts in.
    """
    now = now or datetime.now(UTC)
    if key not in _KEYS:
        raise ValueError(f"unknown demo scenario {key!r}")
    scope = TenantScope(session, DEMO_MERCHANT_ID)
    contact = _contact()
    on_case_ready = (
        (lambda case: dispatch_diagnosis(str(case.case_id))) if dispatch else None
    )

    if key == "payment_failure":
        ev = _event(session, etype="payment.failed",
                    payload=_payment_payload(amount="7900.00", contact=contact,
                                             token=_next("tok")))
        create_or_attach_case(session, event=ev, on_case_ready=on_case_ready)
        case = _case_for_event(session, ev.event_id)
        score_case(session, case, now=now)
        return {"scenario": key, "case_id": str(case.case_id), "status": str(case.status)}

    if key == "checkout_abandonment":
        ev = _event(session, etype="checkout.abandoned",
                    payload=_checkout_payload(value="4300.00", contact=contact))
        create_checkout_case(session, event_id=ev.event_id, on_case_ready=on_case_ready)
        case = _case_for_event(session, ev.event_id)
        score_case(session, case, now=now)
        return {"scenario": key, "case_id": str(case.case_id), "status": str(case.status)}

    if key == "cross_leg_merge":
        # Leg 2 first: the customer abandons checkout with cart_id == X.
        cart_id = _next("cart")
        co_ev = _event(session, etype="checkout.abandoned",
                       payload=_checkout_payload(value="6200.00", contact=contact,
                                                 cart_id=cart_id))
        create_checkout_case(session, event_id=co_ev.event_id)
        abandonment = _case_for_event(session, co_ev.event_id)

        # Leg 1: the same order (order_id == cart_id) then fails as a live retry.
        pay_ev = _event(session, etype="payment.failed",
                        payload=_payment_payload(amount="6200.00", contact=contact,
                                                 token=_next("tok"), order_id=cart_id))
        create_or_attach_case(session, event=pay_ev, on_case_ready=on_case_ready)
        payment_case = _case_for_event(session, pay_ev.event_id)

        session.refresh(abandonment)
        score_case(session, payment_case, now=now)
        return {
            "scenario": key,
            "case_id": str(payment_case.case_id),
            "status": str(payment_case.status),
            "merged_case_id": str(abandonment.case_id),
            "merged": abandonment.superseded_by_case_id == payment_case.case_id,
        }

    if key == "b2b_invoice_bundle":
        # Two overdue invoices for the same counterparty — the §3 grouping rule
        # bundles the second into the case the first one opened; no new case.
        first_ev = _event(session, etype="invoice.overdue",
                          payload=_invoice_payload(original="42000.00", contact=contact))
        ingest_invoice(session, event_id=first_ev.event_id)
        case = _case_for_event(session, first_ev.event_id)
        first_case_id = case.case_id

        second_ev = _event(session, etype="invoice.overdue",
                           payload=_invoice_payload(original="18500.00", contact=contact))
        ingest_invoice(session, event_id=second_ev.event_id, on_case_ready=on_case_ready)

        session.refresh(case)
        score_case(session, case, now=now)
        invoice_count = session.scalar(
            select(func.count()).select_from(B2BInvoice).where(B2BInvoice.case_id == case.case_id)
        )
        return {
            "scenario": key,
            "case_id": str(case.case_id),
            "status": str(case.status),
            "bundled": case.case_id == first_case_id,
            "invoice_count": int(invoice_count or 0),
            "amount_at_risk": str(case.amount_at_risk),
        }

    if key == "hard_stop_mac":
        token = _next("tok")
        ev = _event(session, etype="payment.failed",
                    payload=_payment_payload(amount="8600.00", contact=contact,
                                             token=token, error_code="MAC_03"))
        create_or_attach_case(session, event=ev)
        case = _case_for_event(session, ev.event_id)
        # ingestion already seeded the CardRetryBudget for this token — flip it to
        # the Tier-1 hard-stop state the directive produces.
        budget = session.scalars(
            select(CardRetryBudget)
            .where(CardRetryBudget.merchant_id == DEMO_MERCHANT_ID)
            .where(CardRetryBudget.card_token_hash == token)
        ).first()
        if budget is None:
            budget = CardRetryBudget(
                card_token_hash=token, attempts_used_24h=1, attempts_used_30d=1,
            )
            scope.add(budget)
        budget.hard_stop = True
        budget.hard_stop_reason = HardStopReason.NETWORK_HARD_STOP
        session.flush()
        assert not card_retry_within_budget(
            attempts_used_24h=budget.attempts_used_24h,
            attempts_used_30d=budget.attempts_used_30d, hard_stop=True,
        )
        _diagnose_to_playbook(session, case, root_cause="ISSUER_HARD_DECLINE_FRAUD_SUSPECTED")
        _blocked_action(session, case, block_reason=BlockReason.NETWORK_HARD_STOP)
        score_case(session, case, now=now)
        return {"scenario": key, "case_id": str(case.case_id), "status": str(case.status),
                "block_reason": BlockReason.NETWORK_HARD_STOP.value}

    if key == "upi_retry_cap":
        ev = _event(session, etype="subscription.charged.failed",
                    payload=_sub_payload(amount="9600.00", contact=contact, method="upi"))
        create_subscription_case(session, event=ev)
        case = _case_for_event(session, ev.event_id)
        mandate_id = (case.context or {}).get("mandate_id") or _next("mand")
        budget = session.scalars(
            select(UPIRetryBudget)
            .where(UPIRetryBudget.merchant_id == DEMO_MERCHANT_ID)
            .where(UPIRetryBudget.mandate_id == mandate_id)
        ).first()
        if budget is None:
            budget = UPIRetryBudget(mandate_id=mandate_id)
            scope.add(budget)
        budget.attempts_used = 3  # the 3-retry NPCI cap is reached
        session.flush()
        assert not upi_attempt_gate_open(attempts_used=3, mandate_cancelled_at=None)
        _diagnose_to_playbook(session, case, root_cause="UPI_AUTOPAY_CAP_EXHAUSTED")
        _blocked_action(session, case, block_reason=BlockReason.UPI_RETRY_CAP_EXCEEDED)
        score_case(session, case, now=now)
        return {"scenario": key, "case_id": str(case.case_id), "status": str(case.status),
                "block_reason": BlockReason.UPI_RETRY_CAP_EXCEEDED.value}

    # nach_ceiling
    ev = _event(session, etype="subscription.charged.failed",
                payload=_sub_payload(amount="11200.00", contact=contact, method="nach"))
    create_subscription_case(session, event=ev)
    case = _case_for_event(session, ev.event_id)
    mandate_id = (case.context or {}).get("mandate_id") or _next("mand")
    policy = session.scalars(
        select(NACHRetryPolicy)
        .where(NACHRetryPolicy.merchant_id == DEMO_MERCHANT_ID)
        .where(NACHRetryPolicy.mandate_id == mandate_id)
    ).first()
    if policy is None:
        policy = NACHRetryPolicy(mandate_id=mandate_id)
        scope.add(policy)
    policy.clearing_cycle_status = ClearingCycleStatus.RETURNED
    policy.dishonour_count_this_fy = 3  # the self-imposed 3/cycle ceiling is reached
    session.flush()
    assert not nach_retry_eligible(
        clearing_cycle_status=ClearingCycleStatus.RETURNED,
        dishonour_count_this_fy=3,
        retry_eligible_after=None,
        ceiling=3,
        as_of=now.date(),
    )
    _diagnose_to_playbook(session, case, root_cause="NACH_CLEARING_PENDING")
    _blocked_action(session, case, block_reason=BlockReason.NACH_CEILING_REACHED)
    score_case(session, case, now=now)
    return {"scenario": key, "case_id": str(case.case_id), "status": str(case.status),
            "block_reason": BlockReason.NACH_CEILING_REACHED.value}
