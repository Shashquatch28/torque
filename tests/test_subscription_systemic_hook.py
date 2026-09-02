"""Milestone 8 — the M7c §2.7 systemic-hold hook also applies to Leg-3 cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select

from tests.conftest import razorpay_subscription_body
from torque.enums import CaseStatus
from torque.ingestion.subscription import resolve_subscription_buffered_event
from torque.ingestion.systemic import run_systemic_detection
from torque.models import RevenueLeakCase, SystemicEvent


def _sub_event(make_event, m, **body):
    return make_event(
        m,
        type="subscription.charged.failed",
        raw_payload=json.loads(
            razorpay_subscription_body(event="subscription.charged.failed", **body)
        ),
    )


def _case_for(db, ev):
    return db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.source_event_id == ev.event_id)
    ).one()


def test_subscription_case_created_during_active_event_is_born_held(
    db, make_merchant, make_event, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    run_systemic_detection(db, now=datetime.now(UTC))
    (se,) = db.scalars(
        select(SystemicEvent).where(SystemicEvent.merchant_id == m.merchant_id)
    ).all()

    ev = _sub_event(make_event, m, subscription_id="sub_held")
    resolve_subscription_buffered_event(db, event_id=ev.event_id)

    case = _case_for(db, ev)
    assert case.status is CaseStatus.SYSTEMIC_HOLD
    assert case.systemic_event_id == se.systemic_event_id


def test_subscription_case_without_active_event_stays_detected(db, make_merchant, make_event):
    m = make_merchant()
    ev = _sub_event(make_event, m, subscription_id="sub_free")
    resolve_subscription_buffered_event(db, event_id=ev.event_id)
    case = _case_for(db, ev)
    assert case.status is CaseStatus.DETECTED
    assert case.systemic_event_id is None
