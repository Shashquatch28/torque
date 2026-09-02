"""Milestone 7b — cross-leg dedup / Merge (Blueprint §2.4, Decision D).

Only the live direction is implemented: a `payment.failed` arriving after an
open `CHECKOUT_ABANDONMENT` case. The reverse direction is deferred with Leg-2
ingestion — the last test pins that.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.enums import CaseStatus, LegType
from torque.ingestion.buffer import resolve_buffered_event
from torque.ingestion.cases import create_or_attach_case
from torque.ingestion.dedup import find_supersedable_case
from torque.ingestion.outcomes import BufferOutcome
from torque.models import RevenueLeakCase

ABANDON_CTX = {
    "cart_id": "order_M7B001",
    "cart_value": "499.00",
    "drop_stage": "vpa_entry",
    "payment_method_attempted": "UPI_COLLECT",
}


def _failed_event(make_event, m, **body):
    return make_event(
        m, type="payment.failed", raw_payload=json.loads(razorpay_payment_body(**body))
    )


def _abandon_case(make_case, m, cp, *, status=CaseStatus.DETECTED, opened_at=None, ctx=None):
    kw = {"status": status, "context": dict(ctx or ABANDON_CTX)}
    if opened_at is not None:
        kw["opened_at"] = opened_at
    return make_case(
        merchant=m, counterparty=cp, leg=LegType.CHECKOUT_ABANDONMENT, **kw
    )


def test_matching_abandonment_is_superseded(
    db, make_merchant, make_counterparty, make_case, make_event
):
    m, cp = make_merchant(), make_counterparty()
    aband = _abandon_case(make_case, m, cp)
    ev = _failed_event(make_event, m, order_id="order_M7B001", contact=cp.phone)

    out = create_or_attach_case(db, event=ev)
    assert out is BufferOutcome.CASE_MERGED

    new_case = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
        .where(RevenueLeakCase.leg_type == LegType.PAYMENT_DEGRADATION)
    ).one()
    db.refresh(aband)
    assert aband.superseded_by_case_id == new_case.case_id
    assert aband.status is CaseStatus.DETECTED  # status left untouched — no CANCELLED edge
    assert new_case.superseded_by_case_id is None  # the new case is canonical
    merged = new_case.context["merged_abandonment_context"]
    assert merged["drop_stage"] == "vpa_entry"
    assert merged["payment_method_attempted"] == "UPI_COLLECT"


def test_no_abandonment_creates_normally(db, make_merchant, make_event):
    m = make_merchant()
    ev = _failed_event(make_event, m, order_id="order_lonely")
    assert create_or_attach_case(db, event=ev) is BufferOutcome.CASE_CREATED


def test_abandonment_outside_window_is_not_merged(
    db, make_merchant, make_counterparty, make_case, make_event
):
    m, cp = make_merchant(), make_counterparty()
    _abandon_case(make_case, m, cp, opened_at=datetime.now(UTC) - timedelta(hours=3))
    ev = _failed_event(make_event, m, order_id="order_M7B001", contact=cp.phone)
    assert create_or_attach_case(db, event=ev) is BufferOutcome.CASE_CREATED
    open_cases = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
    ).all()
    assert len(open_cases) == 2


def test_different_counterparty_is_not_merged(
    db, make_merchant, make_counterparty, make_case, make_event
):
    m = make_merchant()
    cp_a = make_counterparty(phone="+91111")
    make_counterparty(phone="+92222")  # the payer — a different identity
    _abandon_case(make_case, m, cp_a)
    ev = _failed_event(make_event, m, order_id="order_M7B001", contact="+92222", email=None)
    # ev resolves to the +92222 identity — not cp_a's abandonment
    assert create_or_attach_case(db, event=ev) is BufferOutcome.CASE_CREATED


def test_different_merchant_is_not_merged(
    db, make_merchant, make_counterparty, make_case, make_event
):
    m1, m2 = make_merchant(), make_merchant()
    cp = make_counterparty()
    _abandon_case(make_case, m1, cp)
    ev = _failed_event(make_event, m2, order_id="order_M7B001", contact=cp.phone)
    assert create_or_attach_case(db, event=ev) is BufferOutcome.CASE_CREATED


def test_terminal_abandonment_is_not_merged(
    db, make_merchant, make_counterparty, make_case, make_event
):
    m, cp = make_merchant(), make_counterparty()
    _abandon_case(make_case, m, cp, status=CaseStatus.CANCELLED)
    ev = _failed_event(make_event, m, order_id="order_M7B001", contact=cp.phone)
    assert create_or_attach_case(db, event=ev) is BufferOutcome.CASE_CREATED


def test_merge_is_idempotent_on_redelivery(
    db, make_merchant, make_counterparty, make_case, make_event
):
    m, cp = make_merchant(), make_counterparty()
    aband = _abandon_case(make_case, m, cp)
    ev = _failed_event(make_event, m, order_id="order_M7B001", contact=cp.phone)

    first = resolve_buffered_event(db, event_id=ev.event_id)
    second = resolve_buffered_event(db, event_id=ev.event_id)
    assert first is BufferOutcome.CASE_MERGED
    assert second is BufferOutcome.NOOP

    payment_cases = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
        .where(RevenueLeakCase.leg_type == LegType.PAYMENT_DEGRADATION)
    ).all()
    assert len(payment_cases) == 1
    db.refresh(aband)
    assert aband.superseded_by_case_id == payment_cases[0].case_id


def test_reverse_direction_is_not_implemented(
    db, make_merchant, make_counterparty, make_case
):
    # An open PAYMENT_DEGRADATION case with a matching cart must NOT be found by
    # the dedup lookup — M7b only supersedes CHECKOUT_ABANDONMENT cases.
    m, cp = make_merchant(), make_counterparty()
    make_case(
        merchant=m,
        counterparty=cp,
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay"},
    )
    found = find_supersedable_case(
        db,
        merchant_id=m.merchant_id,
        counterparty_id=cp.counterparty_id,
        order_id="order_M7B001",
        now=datetime.now(UTC),
    )
    assert found is None
