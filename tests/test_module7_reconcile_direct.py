"""Module 7 §7.1.1 — direct match via `PaymentLink`, and `payment_link.*` row
upkeep (Blueprint line 398 / DEFERRED "Webhook-driven PaymentLink.status …").

A `payment_link.paid` / `.partially_paid` for a link Torque holds a row for →
attribute fully to that link's `case_id`, `recovery_type = AGENT_ASSISTED`.
"""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select

from tests.conftest import razorpay_payment_link_body
from torque.enums import CaseStatus, LegType, PaymentLinkStatus, RecoveryType
from torque.models import Event, PaymentLink
from torque.reconciliation.reconcile import ReconcileOutcome, reconcile_event


def _link_event(db, merchant, *, key, **kw):
    raw = json.loads(razorpay_payment_link_body(**kw))
    ev = Event(
        merchant_id=merchant.merchant_id, type=raw["event"],
        idempotency_key=key, raw_payload=raw,
    )
    db.add(ev)
    db.flush()
    return ev


def test_paid_link_directly_recovers_its_case(
    db, make_case, make_merchant, make_counterparty, make_payment_link
):
    m = make_merchant()
    cp = make_counterparty()
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("499.00"),
    )
    link = make_payment_link(case=case, link_id="plink_D1", status=PaymentLinkStatus.ISSUED)

    ev = _link_event(
        db, m, key="evt_pl_paid_1", event="payment_link.paid",
        link_id="plink_D1", amount_paise=49900,
    )
    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.RECOVERED

    db.refresh(case)
    db.refresh(link)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED  # Torque generated the link
    assert case.recovered_amount == Decimal("499.00")
    assert link.status is PaymentLinkStatus.PAID
    assert link.amount_paid == Decimal("499.00")
    assert link.paid_at is not None


def test_expired_link_updates_row_only(
    db, make_case, make_merchant, make_counterparty, make_payment_link
):
    m = make_merchant()
    case = make_case(
        merchant=m, counterparty=make_counterparty(), leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("300.00"),
    )
    link = make_payment_link(case=case, link_id="plink_D2")
    ev = _link_event(
        db, m, key="evt_pl_exp_1", event="payment_link.expired", link_id="plink_D2"
    )
    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.LINK_UPDATED
    db.refresh(case)
    db.refresh(link)
    assert link.status is PaymentLinkStatus.EXPIRED
    assert link.paid_at is None
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE  # untouched


def test_unknown_link_with_torque_case_ref_creates_row_and_reconciles(
    db, make_case, make_merchant, make_counterparty
):
    m = make_merchant()
    case = make_case(
        merchant=m, counterparty=make_counterparty(), leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("650.00"),
    )
    ev = _link_event(
        db, m, key="evt_pl_ref_1", event="payment_link.paid",
        link_id="plink_D3", amount_paise=65000, torque_case_id=str(case.case_id),
    )
    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.RECOVERED

    link = db.get(PaymentLink, "plink_D3")
    assert link is not None
    assert link.case_id == case.case_id
    assert link.action_id is None  # unattributed to a specific Action
    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED


def test_unknown_link_no_ref_falls_through_to_indirect_match(
    db, make_case, make_merchant, make_counterparty
):
    m = make_merchant()
    cp = make_counterparty(phone="+919866660000")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("800.00"),
    )
    ev = _link_event(
        db, m, key="evt_pl_ind_1", event="payment_link.paid",
        link_id="plink_EXTERNAL", amount_paise=80000, contact="+919866660000",
    )
    outcome = reconcile_event(db, event_id=ev.event_id)
    # no Torque link row, no case ref → indirect match by (merchant, cp, amount)
    assert outcome is ReconcileOutcome.RECOVERED
    assert db.get(PaymentLink, "plink_EXTERNAL") is None  # no row invented
    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    # no Torque Action for the case → self-recovered
    assert case.recovery_type is RecoveryType.SELF_RECOVERED


def test_paid_link_pointing_at_closed_case_only_updates_row(
    db, make_case, make_merchant, make_counterparty, make_payment_link
):
    m = make_merchant()
    case = make_case(
        merchant=m, counterparty=make_counterparty(), leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.RECOVERED, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("100.00"),
    )
    link = make_payment_link(case=case, link_id="plink_D5")
    ev = _link_event(
        db, m, key="evt_pl_closed_1", event="payment_link.paid",
        link_id="plink_D5", amount_paise=10000,
    )
    outcome = reconcile_event(db, event_id=ev.event_id)
    assert outcome is ReconcileOutcome.LINK_UPDATED
    db.refresh(link)
    assert link.status is PaymentLinkStatus.PAID


def test_paid_link_row_update_persists_before_reconciliation(
    db, make_case, make_merchant, make_counterparty, make_payment_link
):
    """Even when the recovery closes the case, the link row's paid state is
    written (Module 9 exception/ROI reporting reads it)."""
    m = make_merchant()
    case = make_case(
        merchant=m, counterparty=make_counterparty(), leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=Decimal("250.00"),
    )
    make_payment_link(case=case, link_id="plink_D6")
    ev = _link_event(
        db, m, key="evt_pl_p_1", event="payment_link.paid",
        link_id="plink_D6", amount_paise=25000,
    )
    reconcile_event(db, event_id=ev.event_id)
    link = db.scalars(select(PaymentLink).where(PaymentLink.link_id == "plink_D6")).one()
    assert link.status is PaymentLinkStatus.PAID
    assert link.amount_paid == Decimal("250.00")
