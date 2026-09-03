"""Module 7 §7.1.3 — multiple open cases match one payment.

* They share one merged-outreach `Action` → re-split its `ActionCase.credit_weight`
  proportional to `amount_at_risk` and recover them all (`AGENT_ASSISTED`).
* They do NOT share a merged `Action` → attribute the payment to the
  most-recently-actioned case as `AMBIGUOUS`, leave the rest open.
"""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.enums import ActionOutcome, ActionType, Actor, CaseStatus, LegType, RecoveryType
from torque.events import write_action_and_event
from torque.events.case_event_writer import Attribution
from torque.models import Action, ActionCase, Event
from torque.reconciliation.reconcile import ReconcileOutcome, reconcile_event


def _capture(db, merchant, *, amount, phone, key):
    raw = json.loads(
        razorpay_payment_body(
            event="payment.captured",
            amount_paise=int(Decimal(str(amount)) * 100),
            contact=phone,
        )
    )
    ev = Event(
        merchant_id=merchant.merchant_id, type="payment.captured",
        idempotency_key=key, raw_payload=raw,
    )
    db.add(ev)
    db.flush()
    return ev


def _merged_action(db, m, primary, secondary, w_primary, w_secondary):
    action = Action(
        merchant_id=m.merchant_id, primary_case_id=primary.case_id, run_id=None,
        action_type=ActionType.SEND_EMAIL, channel="email",
        executed_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        outcome=ActionOutcome.SUCCESS,
    )
    write_action_and_event(
        db, action=action, actor=Actor.AGENT,
        attributions=[
            Attribution(case_id=primary.case_id, is_primary=True, credit_weight=w_primary),
            Attribution(case_id=secondary.case_id, is_primary=False, credit_weight=w_secondary),
        ],
    )
    return action


def test_merged_set_lump_payment_recovers_all_and_resplits_weights(
    db, make_case, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty(phone="+919877770001")
    c1 = make_case(
        merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={},
        status=CaseStatus.PLAYBOOK_ACTIVE, amount_at_risk=Decimal("1000.00"),
    )
    c2 = make_case(
        merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={},
        status=CaseStatus.PLAYBOOK_ACTIVE, amount_at_risk=Decimal("3000.00"),
    )
    # merged outreach — initial split is even; reconciliation re-splits ∝ amount.
    action = _merged_action(db, m, c2, c1, Decimal("0.50000"), Decimal("0.50000"))

    ev = _capture(db, m, amount=Decimal("4000.00"), phone="+919877770001", key="evt_ms_1")
    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.MULTI_RECOVERED

    db.refresh(c1)
    db.refresh(c2)
    assert c1.status is CaseStatus.RECOVERED
    assert c2.status is CaseStatus.RECOVERED
    assert c1.recovery_type is RecoveryType.AGENT_ASSISTED
    assert c2.recovery_type is RecoveryType.AGENT_ASSISTED
    assert c1.recovered_amount == Decimal("1000.00")
    assert c2.recovered_amount == Decimal("3000.00")

    rows = {r.case_id: r for r in db.scalars(
        select(ActionCase).where(ActionCase.action_id == action.action_id)
    ).all()}
    assert sum(r.credit_weight for r in rows.values()) == Decimal("1.00000")
    assert rows[c2.case_id].credit_weight == Decimal("0.75000")  # 3000/4000, primary remainder
    assert rows[c1.case_id].credit_weight == Decimal("0.25000")  # 1000 / 4000


def test_ambiguous_multi_match_attributes_to_one_leaves_rest_open(
    db, make_case, make_merchant, make_counterparty, make_action
):
    m = make_merchant()
    cp = make_counterparty(phone="+919877770002")
    older = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("500.00"),
    )
    newer = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("500.00"),
    )
    make_action(case=newer)  # newer has the most recent Torque action

    ev = _capture(db, m, amount=Decimal("500.00"), phone="+919877770002", key="evt_amb_1")
    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.AMBIGUOUS_RECOVERED

    db.refresh(older)
    db.refresh(newer)
    assert newer.status is CaseStatus.RECOVERED
    assert newer.recovery_type is RecoveryType.AMBIGUOUS
    assert older.status is CaseStatus.PLAYBOOK_ACTIVE  # left open — can't be sure
    assert older.recovery_type is None
