"""Module 2 — shared-engine integrity, four-leg idempotency, causality, tenant
isolation. Whole-module assertions rather than per-file coverage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tests.conftest import (
    checkout_abandoned_body,
    razorpay_invoice_body,
    razorpay_payment_body,
    razorpay_subscription_body,
)
from torque.enums import CaseStatus, LegType
from torque.ingestion.b2b import ingest_invoice
from torque.ingestion.buffer import resolve_buffered_event
from torque.ingestion.checkout import create_checkout_case
from torque.ingestion.outcomes import BufferOutcome
from torque.ingestion.subscription import resolve_subscription_buffered_event
from torque.models import CardRetryBudget, RevenueLeakCase, UPIRetryBudget


def _ev(make_event, m, typ, body):
    return make_event(m, type=typ, raw_payload=json.loads(body))


_CREATED = BufferOutcome.CASE_CREATED
_RECOVERED = BufferOutcome.SELF_RECOVERED


def _cases(db, m, leg=None):
    stmt = select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    if leg is not None:
        stmt = stmt.where(RevenueLeakCase.leg_type == leg)
    return db.scalars(stmt).all()


# --- shared lifecycle: all four legs form a case in DETECTED ---------------


def test_all_four_legs_create_a_detected_case_and_mark_the_event_processed(
    db, make_merchant, make_event
):
    m = make_merchant()

    pf = _ev(make_event, m, "payment.failed", razorpay_payment_body(order_id="o1"))
    assert resolve_buffered_event(db, event_id=pf.event_id) is BufferOutcome.CASE_CREATED

    sf = _ev(make_event, m, "subscription.charged.failed",
             razorpay_subscription_body(subscription_id="s1"))
    assert resolve_subscription_buffered_event(db, event_id=sf.event_id) is _CREATED

    ck = _ev(make_event, m, "checkout.abandoned", checkout_abandoned_body(cart_id="c1"))
    assert create_checkout_case(db, event_id=ck.event_id) is BufferOutcome.CASE_CREATED

    inv = _ev(make_event, m, "invoice.overdue", razorpay_invoice_body(invoice_id="i1"))
    assert ingest_invoice(db, event_id=inv.event_id) is BufferOutcome.CASE_CREATED

    legs = {c.leg_type for c in _cases(db, m)}
    assert legs == {
        LegType.PAYMENT_DEGRADATION,
        LegType.SUBSCRIPTION_FAILURE,
        LegType.CHECKOUT_ABANDONMENT,
        LegType.B2B_RECEIVABLE,
    }
    for c in _cases(db, m):
        assert c.status is CaseStatus.DETECTED
    for e in (pf, sf, ck, inv):
        assert e.processed is True


# --- module-wide idempotency --------------------------------------------


def test_every_leg_is_idempotent_under_redelivery(db, make_merchant, make_event):
    m = make_merchant()
    ops = [
        ("payment.failed", razorpay_payment_body(order_id="o2"),
         lambda e: resolve_buffered_event(db, event_id=e)),
        ("subscription.charged.failed", razorpay_subscription_body(subscription_id="s2"),
         lambda e: resolve_subscription_buffered_event(db, event_id=e)),
        ("checkout.abandoned", checkout_abandoned_body(cart_id="c2"),
         lambda e: create_checkout_case(db, event_id=e)),
        ("invoice.overdue", razorpay_invoice_body(invoice_id="i2"),
         lambda e: ingest_invoice(db, event_id=e)),
    ]
    for typ, body, run in ops:
        ev = _ev(make_event, m, typ, body)
        first = run(ev.event_id)
        second = run(ev.event_id)
        assert first is BufferOutcome.CASE_CREATED
        assert second is BufferOutcome.NOOP

    assert len(_cases(db, m)) == 4  # exactly one per leg, no duplicates


# --- causality / out-of-order -------------------------------------------


def test_payment_self_recovery_creates_no_case(db, make_merchant, make_event):
    m = make_merchant()
    base = datetime.now(UTC)
    fail_body = json.loads(razorpay_payment_body(payment_id="p", order_id="o"))
    ok_body = json.loads(
        razorpay_payment_body(event="payment.captured", payment_id="p", order_id="o")
    )
    pf = make_event(m, type="payment.failed", received_at=base, raw_payload=fail_body)
    make_event(
        m, type="payment.captured",
        received_at=base + timedelta(seconds=2), raw_payload=ok_body,
    )
    assert resolve_buffered_event(db, event_id=pf.event_id) is _RECOVERED
    assert _cases(db, m) == []


def test_subscription_self_recovery_creates_no_case(db, make_merchant, make_event):
    m = make_merchant()
    base = datetime.now(UTC)
    fail_body = json.loads(razorpay_subscription_body(subscription_id="sx"))
    ok_body = json.loads(
        razorpay_subscription_body(event="subscription.charged", subscription_id="sx")
    )
    sf = make_event(
        m, type="subscription.charged.failed", received_at=base, raw_payload=fail_body
    )
    make_event(
        m, type="subscription.charged",
        received_at=base + timedelta(seconds=2), raw_payload=ok_body,
    )
    assert resolve_subscription_buffered_event(db, event_id=sf.event_id) is _RECOVERED
    assert _cases(db, m) == []


def test_abandonment_then_payment_yields_one_canonical_case(db, make_merchant, make_event):
    m = make_merchant()
    ck = _ev(make_event, m, "checkout.abandoned",
             checkout_abandoned_body(cart_id="oz", contact="+9155"))
    create_checkout_case(db, event_id=ck.event_id)
    pf = make_event(m, type="payment.failed",
                    raw_payload=json.loads(razorpay_payment_body(order_id="oz", contact="+9155")))
    resolve_buffered_event(db, event_id=pf.event_id)

    canonical = [c for c in _cases(db, m) if c.superseded_by_case_id is None]
    assert len(canonical) == 1
    assert canonical[0].leg_type is LegType.PAYMENT_DEGRADATION


def test_payment_then_abandonment_yields_one_canonical_case(db, make_merchant, make_event):
    m = make_merchant()
    pf = make_event(m, type="payment.failed",
                    raw_payload=json.loads(razorpay_payment_body(order_id="oy", contact="+9166")))
    resolve_buffered_event(db, event_id=pf.event_id)
    ck = _ev(make_event, m, "checkout.abandoned",
             checkout_abandoned_body(cart_id="oy", contact="+9166"))
    create_checkout_case(db, event_id=ck.event_id)

    canonical = [c for c in _cases(db, m) if c.superseded_by_case_id is None]
    assert len(canonical) == 1
    assert canonical[0].leg_type is LegType.PAYMENT_DEGRADATION


# --- four-leg tenant isolation ----------------------------------------


def test_no_leg_crosses_merchant_boundaries(db, make_merchant, make_event):
    from torque.models import Event

    a, b = make_merchant(), make_merchant()
    contact = "+919900000000"  # same customer contact for both merchants' signals

    _ev(make_event, a, "payment.failed", razorpay_payment_body(order_id="oa", contact=contact))
    _ev(make_event, a, "subscription.charged.failed",
        razorpay_subscription_body(subscription_id="sa", contact=contact, token_id="tok_a"))
    _ev(make_event, a, "checkout.abandoned", checkout_abandoned_body(cart_id="ca", contact=contact))
    _ev(make_event, a, "invoice.overdue", razorpay_invoice_body(invoice_id="ia", contact=contact))

    runners = {
        "payment.failed": lambda e: resolve_buffered_event(db, event_id=e),
        "subscription.charged.failed": lambda e: resolve_subscription_buffered_event(
            db, event_id=e
        ),
        "checkout.abandoned": lambda e: create_checkout_case(db, event_id=e),
        "invoice.overdue": lambda e: ingest_invoice(db, event_id=e),
    }
    for ev in db.scalars(select(Event).where(Event.merchant_id == a.merchant_id)).all():
        runners[ev.type](ev.event_id)

    assert len(_cases(db, a)) == 4  # 4 legs, no merge (no matching cross-leg identity)
    assert _cases(db, b) == []
    assert db.scalars(
        select(UPIRetryBudget).where(UPIRetryBudget.merchant_id == b.merchant_id)
    ).all() == []
    assert db.scalars(
        select(CardRetryBudget).where(CardRetryBudget.merchant_id == b.merchant_id)
    ).all() == []
