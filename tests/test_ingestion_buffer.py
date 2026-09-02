"""Milestone 7b — the §2.3 same-session self-recovery buffer.

Direct tests of `torque.ingestion.buffer.resolve_buffered_event` against the
harness session — the Celery hop is exercised separately in
`test_webhook_dispatch.py`.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.ingestion.buffer import resolve_buffered_event
from torque.ingestion.outcomes import BufferOutcome
from torque.models import RevenueLeakCase


def _payload(**kw) -> dict:
    return json.loads(razorpay_payment_body(**kw))


def _failed(make_event, m, *, received_at=None, **body):
    kw = {"type": "payment.failed", "raw_payload": _payload(event="payment.failed", **body)}
    if received_at is not None:
        kw["received_at"] = received_at
    return make_event(m, **kw)


def _cases(db, merchant_id):
    return list(
        db.scalars(select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == merchant_id))
    )


def test_no_capture_creates_case(db, make_merchant, make_event):
    m = make_merchant()
    ev = _failed(make_event, m)
    out = resolve_buffered_event(db, event_id=ev.event_id)
    assert out is BufferOutcome.CASE_CREATED
    assert len(_cases(db, m.merchant_id)) == 1
    assert ev.processed is True


def test_interim_capture_self_recovers_on_payment_id(db, make_merchant, make_event):
    m = make_merchant()
    base = datetime.now(UTC)
    ev = _failed(make_event, m, received_at=base, payment_id="pay_X", order_id="order_X")
    make_event(
        m,
        type="payment.captured",
        received_at=base + timedelta(seconds=5),
        raw_payload=_payload(event="payment.captured", payment_id="pay_X", order_id="order_DIFF"),
    )
    out = resolve_buffered_event(db, event_id=ev.event_id)
    assert out is BufferOutcome.SELF_RECOVERED
    assert _cases(db, m.merchant_id) == []
    assert ev.processed is True


def test_interim_capture_self_recovers_on_order_id(db, make_merchant, make_event):
    m = make_merchant()
    base = datetime.now(UTC)
    ev = _failed(make_event, m, received_at=base, payment_id="pay_A", order_id="order_SHARED")
    make_event(
        m,
        type="payment.captured",
        received_at=base,  # equal instant still counts (later-or-equal)
        raw_payload=_payload(event="payment.captured", payment_id="pay_B", order_id="order_SHARED"),
    )
    assert resolve_buffered_event(db, event_id=ev.event_id) is BufferOutcome.SELF_RECOVERED


def test_capture_for_other_merchant_is_ignored(db, make_merchant, make_event):
    m1, m2 = make_merchant(), make_merchant()
    base = datetime.now(UTC)
    ev = _failed(make_event, m1, received_at=base, payment_id="pay_M", order_id="order_M")
    make_event(
        m2,
        type="payment.captured",
        received_at=base + timedelta(seconds=1),
        raw_payload=_payload(event="payment.captured", payment_id="pay_M", order_id="order_M"),
    )
    assert resolve_buffered_event(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED
    assert len(_cases(db, m1.merchant_id)) == 1


def test_capture_for_a_different_payment_is_ignored(db, make_merchant, make_event):
    m = make_merchant()
    base = datetime.now(UTC)
    ev = _failed(make_event, m, received_at=base, payment_id="pay_1", order_id="order_1")
    make_event(
        m,
        type="payment.captured",
        received_at=base + timedelta(seconds=1),
        raw_payload=_payload(event="payment.captured", payment_id="pay_2", order_id="order_2"),
    )
    assert resolve_buffered_event(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED


def test_capture_before_the_failure_is_ignored(db, make_merchant, make_event):
    m = make_merchant()
    base = datetime.now(UTC)
    ev = _failed(make_event, m, received_at=base, payment_id="pay_1", order_id="order_1")
    make_event(
        m,
        type="payment.captured",
        received_at=base - timedelta(minutes=1),  # arrived earlier — not "in the interim"
        raw_payload=_payload(event="payment.captured", payment_id="pay_1", order_id="order_1"),
    )
    assert resolve_buffered_event(db, event_id=ev.event_id) is BufferOutcome.CASE_CREATED
    assert len(_cases(db, m.merchant_id)) == 1


def test_already_processed_event_is_noop(db, make_merchant, make_event):
    m = make_merchant()
    ev = _failed(make_event, m)
    ev.processed = True
    db.flush()
    assert resolve_buffered_event(db, event_id=ev.event_id) is BufferOutcome.NOOP
    assert _cases(db, m.merchant_id) == []


def test_missing_event_is_noop(db):
    assert resolve_buffered_event(db, event_id=uuid.uuid4()) is BufferOutcome.NOOP


def test_non_payment_failed_event_is_noop(db, make_merchant, make_event):
    m = make_merchant()
    ev = make_event(
        m, type="payment.captured", raw_payload=_payload(event="payment.captured")
    )
    assert resolve_buffered_event(db, event_id=ev.event_id) is BufferOutcome.NOOP


def test_redelivery_is_idempotent(db, make_merchant, make_event):
    m = make_merchant()
    ev = _failed(make_event, m)
    first = resolve_buffered_event(db, event_id=ev.event_id)
    second = resolve_buffered_event(db, event_id=ev.event_id)
    assert first is BufferOutcome.CASE_CREATED
    assert second is BufferOutcome.NOOP
    assert len(_cases(db, m.merchant_id)) == 1


def test_case_already_exists_for_event_is_noop(db, make_merchant, make_event, make_counterparty):
    from torque.enums import CaseStatus, LegType
    from torque.models import RevenueLeakCase as RLC

    m = make_merchant()
    ev = _failed(make_event, m)
    cp = make_counterparty()
    db.add(
        RLC(
            merchant_id=m.merchant_id,
            leg_type=LegType.PAYMENT_DEGRADATION,
            source_event_id=ev.event_id,
            counterparty_id=cp.counterparty_id,
            amount_at_risk=100,
            status=CaseStatus.DETECTED,
            context={"gateway": "razorpay"},
        )
    )
    db.flush()
    assert resolve_buffered_event(db, event_id=ev.event_id) is BufferOutcome.NOOP
    assert len(_cases(db, m.merchant_id)) == 1
    assert ev.processed is True
