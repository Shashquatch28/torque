"""Milestone 8 — the §2.3 self-recovery buffer for `subscription.charged.failed`
(30 s). Direct tests of `torque.ingestion.subscription.resolve_subscription_buffered_event`."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tests.conftest import razorpay_subscription_body
from torque.enums import LegType
from torque.ingestion.outcomes import BufferOutcome
from torque.ingestion.subscription import resolve_subscription_buffered_event
from torque.models import RevenueLeakCase


def _payload(**kw) -> dict:
    return json.loads(razorpay_subscription_body(**kw))


def _failed(make_event, m, *, received_at=None, **body):
    kw = {
        "type": "subscription.charged.failed",
        "raw_payload": _payload(event="subscription.charged.failed", **body),
    }
    if received_at is not None:
        kw["received_at"] = received_at
    return make_event(m, **kw)


def _cases(db, merchant_id):
    return list(
        db.scalars(
            select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == merchant_id)
        )
    )


def test_no_interim_charge_creates_case(db, make_merchant, make_event):
    m = make_merchant()
    ev = _failed(make_event, m)
    out = resolve_subscription_buffered_event(db, event_id=ev.event_id)
    assert out is BufferOutcome.CASE_CREATED
    cases = _cases(db, m.merchant_id)
    assert len(cases) == 1 and cases[0].leg_type is LegType.SUBSCRIPTION_FAILURE
    assert ev.processed is True


def test_interim_charge_self_recovers(db, make_merchant, make_event):
    m = make_merchant()
    base = datetime.now(UTC)
    ev = _failed(make_event, m, received_at=base, subscription_id="sub_X")
    make_event(
        m,
        type="subscription.charged",
        received_at=base + timedelta(seconds=5),
        raw_payload=_payload(event="subscription.charged", subscription_id="sub_X"),
    )
    out = resolve_subscription_buffered_event(db, event_id=ev.event_id)
    assert out is BufferOutcome.SELF_RECOVERED
    assert _cases(db, m.merchant_id) == []
    assert ev.processed is True


def test_interim_charge_for_other_subscription_is_ignored(db, make_merchant, make_event):
    m = make_merchant()
    base = datetime.now(UTC)
    ev = _failed(make_event, m, received_at=base, subscription_id="sub_A")
    make_event(
        m,
        type="subscription.charged",
        received_at=base + timedelta(seconds=1),
        raw_payload=_payload(event="subscription.charged", subscription_id="sub_B"),
    )
    out = resolve_subscription_buffered_event(db, event_id=ev.event_id)
    assert out is BufferOutcome.CASE_CREATED


def test_interim_charge_for_other_merchant_is_ignored(db, make_merchant, make_event):
    m1, m2 = make_merchant(), make_merchant()
    base = datetime.now(UTC)
    ev = _failed(make_event, m1, received_at=base, subscription_id="sub_M")
    make_event(
        m2,
        type="subscription.charged",
        received_at=base + timedelta(seconds=1),
        raw_payload=_payload(event="subscription.charged", subscription_id="sub_M"),
    )
    out = resolve_subscription_buffered_event(db, event_id=ev.event_id)
    assert out is BufferOutcome.CASE_CREATED
    assert len(_cases(db, m1.merchant_id)) == 1


def test_charge_before_the_failure_is_ignored(db, make_merchant, make_event):
    m = make_merchant()
    base = datetime.now(UTC)
    ev = _failed(make_event, m, received_at=base, subscription_id="sub_1")
    make_event(
        m,
        type="subscription.charged",
        received_at=base - timedelta(minutes=1),
        raw_payload=_payload(event="subscription.charged", subscription_id="sub_1"),
    )
    out = resolve_subscription_buffered_event(db, event_id=ev.event_id)
    assert out is BufferOutcome.CASE_CREATED


def test_already_processed_is_noop(db, make_merchant, make_event):
    m = make_merchant()
    ev = _failed(make_event, m)
    ev.processed = True
    db.flush()
    assert resolve_subscription_buffered_event(db, event_id=ev.event_id) is BufferOutcome.NOOP
    assert _cases(db, m.merchant_id) == []


def test_missing_event_is_noop(db):
    assert resolve_subscription_buffered_event(db, event_id=uuid.uuid4()) is BufferOutcome.NOOP


def test_wrong_event_type_is_noop(db, make_merchant, make_event):
    m = make_merchant()
    ev = make_event(m, type="payment.failed", raw_payload={"event": "payment.failed"})
    assert resolve_subscription_buffered_event(db, event_id=ev.event_id) is BufferOutcome.NOOP


def test_redelivery_is_idempotent(db, make_merchant, make_event):
    m = make_merchant()
    ev = _failed(make_event, m)
    first = resolve_subscription_buffered_event(db, event_id=ev.event_id)
    second = resolve_subscription_buffered_event(db, event_id=ev.event_id)
    assert first is BufferOutcome.CASE_CREATED
    assert second is BufferOutcome.NOOP
    assert len(_cases(db, m.merchant_id)) == 1


def test_case_already_exists_is_noop(db, make_merchant, make_event, make_counterparty):
    from torque.enums import CaseStatus
    from torque.models import RevenueLeakCase as RLC

    m = make_merchant()
    ev = _failed(make_event, m)
    cp = make_counterparty()
    db.add(
        RLC(
            merchant_id=m.merchant_id,
            leg_type=LegType.SUBSCRIPTION_FAILURE,
            source_event_id=ev.event_id,
            counterparty_id=cp.counterparty_id,
            amount_at_risk=100,
            status=CaseStatus.DETECTED,
            context={
                "mandate_id": "m",
                "mandate_type": "UPI_AUTOPAY",
                "billing_cycle": "1",
                "subscription_id": "s",
            },
        )
    )
    db.flush()
    assert resolve_subscription_buffered_event(db, event_id=ev.event_id) is BufferOutcome.NOOP
    assert len(_cases(db, m.merchant_id)) == 1
    assert ev.processed is True
