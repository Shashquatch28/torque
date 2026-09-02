"""Module 2 — bidirectional cross-leg correlation (Blueprint §2.4, Decision D).

The forward direction (`payment.failed` after an open `CHECKOUT_ABANDONMENT`
case) is covered in `test_cross_leg_dedup.py` (Leg 1). Here: the **reverse**
direction — `checkout.abandoned` after an open `PAYMENT_DEGRADATION` case — plus
symmetry.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tests.conftest import checkout_abandoned_body, razorpay_payment_body
from torque.enums import CaseStatus, LegType
from torque.ingestion.buffer import resolve_buffered_event
from torque.ingestion.checkout import create_checkout_case
from torque.ingestion.outcomes import BufferOutcome
from torque.models import RevenueLeakCase

CART = "order_shared_1"


def _payment_case(db, make_event, m, *, order_id=CART, contact="+919000000000"):
    ev = make_event(
        m,
        type="payment.failed",
        raw_payload=json.loads(
            razorpay_payment_body(event="payment.failed", order_id=order_id, contact=contact)
        ),
    )
    resolve_buffered_event(db, event_id=ev.event_id)
    return db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
        .where(RevenueLeakCase.leg_type == LegType.PAYMENT_DEGRADATION)
    ).one()


def _checkout_event(make_event, m, *, cart_id=CART, contact="+919000000000"):
    return make_event(
        m,
        type="checkout.abandoned",
        raw_payload=json.loads(checkout_abandoned_body(cart_id=cart_id, contact=contact)),
    )


def test_abandonment_after_payment_case_is_superseded_into_it(db, make_merchant, make_event):
    m = make_merchant()
    payment_case = _payment_case(db, make_event, m)
    ev = _checkout_event(make_event, m)

    out = create_checkout_case(db, event_id=ev.event_id)
    assert out is BufferOutcome.CASE_MERGED

    abandonment = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
        .where(RevenueLeakCase.leg_type == LegType.CHECKOUT_ABANDONMENT)
    ).one()
    db.refresh(payment_case)
    assert abandonment.superseded_by_case_id == payment_case.case_id
    assert abandonment.status is CaseStatus.DETECTED  # status unchanged
    assert payment_case.superseded_by_case_id is None  # payment case stays canonical
    merged = payment_case.context["merged_abandonment_context"]
    assert merged["cart_id"] == CART
    assert merged["drop_stage"] == "vpa_entry"
    assert ev.processed is True


def test_no_matching_payment_case_creates_canonical_abandonment(db, make_merchant, make_event):
    m = make_merchant()
    _payment_case(db, make_event, m, order_id="order_other")
    ev = _checkout_event(make_event, m, cart_id="order_unrelated")
    assert create_checkout_case(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED
    aband = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.leg_type == LegType.CHECKOUT_ABANDONMENT)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()
    assert aband.superseded_by_case_id is None


def test_payment_case_outside_window_is_not_matched(db, make_merchant, make_event):
    m = make_merchant()
    payment_case = _payment_case(db, make_event, m)
    payment_case.opened_at = datetime.now(UTC) - timedelta(hours=3)
    db.flush()
    ev = _checkout_event(make_event, m)
    assert create_checkout_case(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED


def test_different_counterparty_is_not_matched(db, make_merchant, make_event):
    m = make_merchant()
    _payment_case(db, make_event, m, contact="+911111")
    ev = _checkout_event(make_event, m, contact="+912222")
    assert create_checkout_case(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED


def test_different_merchant_is_not_matched(db, make_merchant, make_event):
    m1, m2 = make_merchant(), make_merchant()
    _payment_case(db, make_event, m1)
    ev = _checkout_event(make_event, m2)
    assert create_checkout_case(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED
    assert (
        db.scalars(
            select(RevenueLeakCase)
            .where(RevenueLeakCase.merchant_id == m2.merchant_id)
            .where(RevenueLeakCase.leg_type == LegType.PAYMENT_DEGRADATION)
        ).all()
        == []
    )


def test_terminal_payment_case_is_not_matched(db, make_merchant, make_event):
    m = make_merchant()
    payment_case = _payment_case(db, make_event, m)
    payment_case.status = CaseStatus.RECOVERED  # raw set — terminal
    db.flush()
    ev = _checkout_event(make_event, m)
    assert create_checkout_case(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED


def test_already_superseded_payment_case_is_not_matched(db, make_merchant, make_event, make_case):
    m = make_merchant()
    payment_case = _payment_case(db, make_event, m)
    other = make_case(merchant=m)
    payment_case.superseded_by_case_id = other.case_id
    db.flush()
    ev = _checkout_event(make_event, m)
    assert create_checkout_case(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED


def test_reverse_merge_is_idempotent_on_redelivery(db, make_merchant, make_event):
    m = make_merchant()
    payment_case = _payment_case(db, make_event, m)
    ev = _checkout_event(make_event, m)
    first = create_checkout_case(db, event_id=ev.event_id)
    second = create_checkout_case(db, event_id=ev.event_id)
    assert first is BufferOutcome.CASE_MERGED
    assert second is BufferOutcome.NOOP
    abandonments = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
        .where(RevenueLeakCase.leg_type == LegType.CHECKOUT_ABANDONMENT)
    ).all()
    assert len(abandonments) == 1
    db.refresh(payment_case)
    assert abandonments[0].superseded_by_case_id == payment_case.case_id


def test_symmetry_forward_and_reverse_reach_the_same_shape(db, make_merchant, make_event):
    # forward: abandonment first, then payment.failed
    mf = make_merchant()
    ab_ev = _checkout_event(make_event, mf, cart_id="order_fwd", contact="+913333")
    create_checkout_case(db, event_id=ab_ev.event_id)  # canonical abandonment
    pf_ev = make_event(
        mf,
        type="payment.failed",
        raw_payload=json.loads(
            razorpay_payment_body(event="payment.failed", order_id="order_fwd", contact="+913333")
        ),
    )
    resolve_buffered_event(db, event_id=pf_ev.event_id)

    fwd_payment = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == mf.merchant_id)
        .where(RevenueLeakCase.leg_type == LegType.PAYMENT_DEGRADATION)
    ).one()
    fwd_aband = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == mf.merchant_id)
        .where(RevenueLeakCase.leg_type == LegType.CHECKOUT_ABANDONMENT)
    ).one()

    # reverse: payment.failed first, then abandonment
    mr = make_merchant()
    rev_payment = _payment_case(db, make_event, mr, order_id="order_rev", contact="+914444")
    rev_ab_ev = _checkout_event(make_event, mr, cart_id="order_rev", contact="+914444")
    create_checkout_case(db, event_id=rev_ab_ev.event_id)
    rev_aband = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == mr.merchant_id)
        .where(RevenueLeakCase.leg_type == LegType.CHECKOUT_ABANDONMENT)
    ).one()
    db.refresh(rev_payment)

    # identical end state: abandonment superseded into the canonical payment case,
    # payment case carries merged_abandonment_context, abandonment keeps DETECTED
    for payment, aband in ((fwd_payment, fwd_aband), (rev_payment, rev_aband)):
        assert aband.superseded_by_case_id == payment.case_id
        assert payment.superseded_by_case_id is None
        assert aband.status is CaseStatus.DETECTED
        assert payment.context.get("merged_abandonment_context") is not None
