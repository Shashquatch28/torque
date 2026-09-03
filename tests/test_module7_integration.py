"""Module 7 — the webhook → reconciliation hand-off (Blueprint §7.3).

A verified success `Event` from Module 2's pipeline is dispatched to
`reconcile_event_task`. No new webhook path; no buffer.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select

from tests.conftest import (
    WEBHOOK_TEST_SECRET,
    razorpay_payment_body,
    razorpay_payment_link_body,
    razorpay_subscription_body,
)
from torque.enums import CaseStatus, LegType, RecoveryType
from torque.models import Event, RevenueLeakCase
from torque.reconciliation.reconcile import reconcile_event
from torque.security.razorpay_signature import compute_razorpay_signature

SIG = "X-Razorpay-Signature"
EVID = "X-Razorpay-Event-Id"


def _headers(raw: bytes, event_id: str) -> dict[str, str]:
    return {
        SIG: compute_razorpay_signature(raw, WEBHOOK_TEST_SECRET),
        EVID: event_id,
        "Content-Type": "application/json",
    }


def test_payment_captured_enqueues_reconcile_not_the_buffer(api_client, db, make_merchant):
    m = make_merchant()
    raw = razorpay_payment_body(event="payment.captured")
    r = api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_i_pc_1")
    )
    assert r.status_code == 200
    (ev,) = db.scalars(select(Event).where(Event.merchant_id == m.merchant_id)).all()
    api_client.reconcile_enqueue.assert_called_once()
    args, _kw = api_client.reconcile_enqueue.call_args
    assert args[0] == (str(ev.event_id),)
    api_client.buffer_enqueue.assert_not_called()


def test_payment_link_and_subscription_charged_enqueue_reconcile(api_client, db, make_merchant):
    m = make_merchant()
    for raw, key in (
        (razorpay_payment_link_body(event="payment_link.paid"), "evt_i_pl_1"),
        (razorpay_subscription_body(event="subscription.charged"), "evt_i_sc_1"),
    ):
        api_client.post(
            f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, key)
        )
    assert api_client.reconcile_enqueue.call_count == 2


def test_eager_end_to_end_capture_recovers_the_case(
    make_api_client, db, make_merchant, make_counterparty, make_case, make_action,
    celery_eager, monkeypatch,
):
    @contextmanager
    def _fake_scope():
        yield db

    monkeypatch.setattr("torque.reconciliation.tasks._session_scope", _fake_scope)
    client = make_api_client(patch_enqueue=False)

    m = make_merchant()
    cp = make_counterparty(phone="+919810000001")
    case = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE, context={"gateway": "razorpay"},
        amount_at_risk=__import__("decimal").Decimal("499.00"),
    )
    make_action(case=case)

    raw = razorpay_payment_body(
        event="payment.captured", amount_paise=49900, contact="+919810000001"
    )
    r = client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=raw, headers=_headers(raw, "evt_i_e2e_1")
    )
    assert r.status_code == 200

    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED


def test_reconcile_after_ingestion_created_case(
    api_client, db, make_merchant, celery_eager, monkeypatch
):
    """A `payment.failed` becomes a DETECTED case (Module 2), then a
    `payment.captured` for the same counterparty/amount arrives → §7.1.4 closes
    it CANCELLED / SELF_RECOVERED (customer self-paid before diagnosis)."""
    from torque.ingestion.buffer import resolve_buffered_event

    m = make_merchant()
    failed = razorpay_payment_body(
        event="payment.failed", amount_paise=55500, contact="+919810000009"
    )
    api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=failed, headers=_headers(failed, "evt_i_f_1")
    )
    (fev,) = db.scalars(
        select(Event)
        .where(Event.merchant_id == m.merchant_id)
        .where(Event.type == "payment.failed")
    ).all()
    resolve_buffered_event(db, event_id=fev.event_id)  # what the buffer task runs
    case = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()
    assert case.status is CaseStatus.DETECTED

    captured = razorpay_payment_body(
        event="payment.captured", amount_paise=55500, contact="+919810000009"
    )
    api_client.post(
        f"/webhooks/razorpay/{m.merchant_id}", content=captured,
        headers=_headers(captured, "evt_i_c_1"),
    )
    cev = db.scalars(
        select(Event)
        .where(Event.merchant_id == m.merchant_id)
        .where(Event.type == "payment.captured")
    ).one()
    reconcile_event(db, event_id=cev.event_id)

    db.refresh(case)
    assert case.status is CaseStatus.CANCELLED
    assert case.recovery_type is RecoveryType.SELF_RECOVERED
