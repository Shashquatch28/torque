"""Module 12a — closing the autonomous loop (D-137).

Proves the ingestion -> diagnosis -> policy-activation -> execution-scheduling
chain now runs on its own, using only the existing, independently-tested
engines (Module 2/3/4/5) wired at their existing extension points:

* ingestion (the Celery task layer) dispatches `torque.diagnosis.diagnose_case_task`
  for the canonical case it just committed (`torque.ingestion.tasks.dispatch_diagnosis`);
* `diagnose_case_task` dispatches `torque.policy.activate_case_task` iff the
  outcome is `ROUTED_TO_PLAYBOOK` (`torque.diagnosis.tasks._dispatch_activation`);
* `activate_case_task` arms the new run's first timer
  (`torque.execution.scheduler.schedule_run`) in the SAME transaction, iff the
  outcome is `RUN_CREATED` — no new Celery hop for this link (D-090 unchanged:
  Postgres-polling stays the durable execution driver; the existing 10s/60s beat
  pollers, untouched, are what actually run it).

No engine logic is duplicated here; every assertion is against the real,
existing tables (`RevenueLeakCase`, `PlaybookRun`, `ScheduledJob`).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import func, select

from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import CaseStatus, LegType
from torque.ingestion.b2b import ingest_invoice
from torque.ingestion.cases import create_or_attach_case
from torque.ingestion.tasks import (
    create_checkout_case_task,
    ingest_invoice_task,
    resolve_buffered_event_task,
)
from torque.models import Event, PlaybookRun, RevenueLeakCase, ScheduledJob
from torque.policy.catalog import seed_catalog

# --- realistic raw payloads (no HTTP layer needed — these feed Event.raw_payload) --


def _pf_payload(*, payment_id, order_id, contact, error_code="BAD_REQUEST_ERROR"):
    return {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": payment_id, "amount": 50000, "currency": "INR", "method": "card",
            "contact": contact, "email": f"{contact.strip('+')}@x.test",
            "error_code": error_code, "order_id": order_id, "token_id": f"tok_{payment_id}",
        }}},
    }


def _co_payload(*, cart_id, contact):
    return {
        "event": "checkout.abandoned",
        "payload": {"checkout": {"entity": {
            "cart_id": cart_id, "cart_value": 50000, "drop_stage": "vpa_entry",
            "payment_method_attempted": "UPI_COLLECT",
            "contact": contact, "email": f"{contact.strip('+')}@x.test",
        }}},
    }


def _inv_payload(*, invoice_id, contact, amount=100000):
    return {
        "event": "invoice.overdue",
        "payload": {"invoice": {"entity": {
            "id": invoice_id, "amount": amount, "amount_paid": 0, "currency": "INR",
            "expire_by": 1_700_000_000,
            "customer_details": {"contact": contact, "email": f"{contact.strip('+')}@x.test"},
        }}},
    }


def _event(db, m, *, type_, key, payload):
    ev = Event(merchant_id=m.merchant_id, type=type_, idempotency_key=key, raw_payload=payload)
    db.add(ev)
    db.flush()
    return ev


@contextmanager
def _bound(db):
    yield db


@pytest.fixture()
def bound(db, monkeypatch, celery_eager):
    """Bind every Module 12a task's `_session_scope` to the harness session (so
    a chained dispatch operates on the SAME transaction the test asserts
    against, not an invisible second connection) and run Celery eagerly (so a
    real, un-spied `apply_async` hop — diagnosis -> policy — executes inline
    instead of trying to reach a real broker)."""

    def _scope():
        return _bound(db)

    monkeypatch.setattr("torque.ingestion.tasks._session_scope", _scope)
    monkeypatch.setattr("torque.diagnosis.tasks._session_scope", _scope)
    monkeypatch.setattr("torque.policy.tasks._session_scope", _scope)
    return db


# --- A. ingestion -> diagnosis -----------------------------------------------


def test_successful_ingestion_dispatches_diagnosis_for_the_new_case(
    db, make_merchant, monkeypatch, bound
):
    m = make_merchant()
    dispatched: list[str] = []
    monkeypatch.setattr(
        "torque.ingestion.tasks.dispatch_diagnosis", lambda cid: dispatched.append(cid)
    )
    ev = _event(db, m, type_="payment.failed", key="pf1",
               payload=_pf_payload(payment_id="pay_1", order_id="ord_1", contact="+919999000001"))

    resolve_buffered_event_task(str(ev.event_id))

    case = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()
    assert dispatched == [str(case.case_id)]


def test_dispatch_carries_the_canonical_case_on_a_reverse_merge(
    db, make_merchant, monkeypatch, bound
):
    """checkout.abandoned arriving after an open PAYMENT_DEGRADATION case: the
    SUPERSEDED (new) checkout case must NOT be the one diagnosis is dispatched
    for — the pre-existing, still-canonical payment case must be."""
    m = make_merchant()
    contact = "+919999000002"
    pay_ev = _event(db, m, type_="payment.failed", key="pf2",
                    payload=_pf_payload(payment_id="pay_2", order_id="cart_2", contact=contact))
    create_or_attach_case(db, event=pay_ev)
    payment_case = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.source_event_id == pay_ev.event_id)
    ).one()

    dispatched: list[str] = []
    monkeypatch.setattr(
        "torque.ingestion.tasks.dispatch_diagnosis", lambda cid: dispatched.append(cid)
    )
    co_ev = _event(db, m, type_="checkout.abandoned", key="co2",
                   payload=_co_payload(cart_id="cart_2", contact=contact))

    create_checkout_case_task(str(co_ev.event_id))

    assert dispatched == [str(payment_case.case_id)]  # never the superseded one


def test_b2b_attach_dispatches_for_the_bundled_case_not_a_new_one(
    db, make_merchant, monkeypatch, bound
):
    m = make_merchant()
    contact = "+919999000003"
    first = _event(db, m, type_="invoice.overdue", key="inv1",
                  payload=_inv_payload(invoice_id="inv_a", contact=contact))
    ingest_invoice(db, event_id=first.event_id)
    case = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()

    dispatched: list[str] = []
    monkeypatch.setattr(
        "torque.ingestion.tasks.dispatch_diagnosis", lambda cid: dispatched.append(cid)
    )
    second = _event(db, m, type_="invoice.overdue", key="inv2",
                   payload=_inv_payload(invoice_id="inv_b", contact=contact, amount=40000))

    ingest_invoice_task(str(second.event_id))

    assert dispatched == [str(case.case_id)]
    assert db.scalar(
        select(func.count()).select_from(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
    ) == 1  # bundled, not a second case


def test_duplicate_ingestion_does_not_dispatch_twice(db, make_merchant, monkeypatch, bound):
    """Event-level redelivery: the second call is ingestion's own existing
    idempotency (NOOP, case already exists) — dispatch must not fire again."""
    m = make_merchant()
    dispatched: list[str] = []
    monkeypatch.setattr(
        "torque.ingestion.tasks.dispatch_diagnosis", lambda cid: dispatched.append(cid)
    )
    ev = _event(db, m, type_="payment.failed", key="pf_dup",
               payload=_pf_payload(payment_id="pay_d", order_id="ord_d", contact="+919999000004"))

    resolve_buffered_event_task(str(ev.event_id))
    resolve_buffered_event_task(str(ev.event_id))  # redelivery

    assert len(dispatched) == 1


def test_noop_ingestion_never_dispatches(db, make_merchant, monkeypatch, bound):
    """An unrelated / wrong-type event never creates a case, so it must never
    dispatch diagnosis."""
    m = make_merchant()
    dispatched: list[str] = []
    monkeypatch.setattr(
        "torque.ingestion.tasks.dispatch_diagnosis", lambda cid: dispatched.append(cid)
    )
    ev = _event(db, m, type_="payment.captured", key="pc1", payload={"event": "payment.captured"})

    resolve_buffered_event_task(str(ev.event_id))

    assert dispatched == []


# --- B. diagnosis -> policy ---------------------------------------------------


def test_routed_to_playbook_dispatches_activation(db, make_case, monkeypatch, bound):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "insufficient_funds"},
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        "torque.diagnosis.tasks._dispatch_activation", lambda cid: dispatched.append(cid)
    )
    from torque.diagnosis.tasks import diagnose_case_task

    result = diagnose_case_task(str(case.case_id))
    assert result == "ROUTED_TO_PLAYBOOK"
    assert dispatched == [str(case.case_id)]


def test_escalated_diagnosis_does_not_dispatch_activation(db, make_case, monkeypatch, bound):
    """A confidently-escalated case is done — a human takes it. Nothing to
    activate."""
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay"},  # no decline_code -> low confidence
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        "torque.diagnosis.tasks._dispatch_activation", lambda cid: dispatched.append(cid)
    )
    from torque.diagnosis.tasks import diagnose_case_task

    result = diagnose_case_task(str(case.case_id))
    assert result == "ESCALATED"
    assert dispatched == []


def test_diagnosis_noop_does_not_dispatch_activation(db, make_case, monkeypatch, bound):
    case = make_case(leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.RECOVERED,
                     context={"gateway": "razorpay"})
    dispatched: list[str] = []
    monkeypatch.setattr(
        "torque.diagnosis.tasks._dispatch_activation", lambda cid: dispatched.append(cid)
    )
    from torque.diagnosis.tasks import diagnose_case_task

    result = diagnose_case_task(str(case.case_id))
    assert result == "NOOP"
    assert dispatched == []


def test_redelivered_diagnosis_dispatches_activation_at_most_once(
    db, make_case, monkeypatch, bound
):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "insufficient_funds"},
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        "torque.diagnosis.tasks._dispatch_activation", lambda cid: dispatched.append(cid)
    )
    from torque.diagnosis.tasks import diagnose_case_task

    diagnose_case_task(str(case.case_id))
    second = diagnose_case_task(str(case.case_id))  # redelivery: already diagnosed
    assert dispatched == [str(case.case_id)]  # exactly once
    assert second == "NOOP"


# --- C. policy -> execution ---------------------------------------------------


def test_run_created_arms_exactly_one_scheduled_job(db, make_case, bound):
    seed_catalog(db)
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value,
        diagnosis_confidence=0.9, context={"gateway": "razorpay"},
    )
    from torque.policy.tasks import activate_case_task

    result = activate_case_task(str(case.case_id))
    assert result == "RUN_CREATED"
    run = db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).one()
    jobs = db.scalars(select(ScheduledJob).where(ScheduledJob.run_id == run.run_id)).all()
    assert len(jobs) == 1


def test_no_playbook_escalation_schedules_nothing(db, make_case, bound):
    """A root cause with no catalog playbook escalates — no run, nothing to
    schedule (existing D-086 behaviour, unchanged)."""
    seed_catalog(db)
    case = make_case(
        leg=LegType.B2B_RECEIVABLE, status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code="DISPUTE_SUSPECTED", diagnosis_confidence=0.4, context={},
    )
    from torque.policy.tasks import activate_case_task

    result = activate_case_task(str(case.case_id))
    assert result == "ESCALATED_NO_PLAYBOOK"
    assert db.scalar(select(func.count()).select_from(ScheduledJob)) == 0


def test_redelivered_activation_does_not_duplicate_the_run_or_job(db, make_case, bound):
    seed_catalog(db)
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value,
        diagnosis_confidence=0.9, context={"gateway": "razorpay"},
    )
    from torque.policy.tasks import activate_case_task

    first = activate_case_task(str(case.case_id))
    second = activate_case_task(str(case.case_id))  # redelivery
    assert first == "RUN_CREATED"
    assert second == "NOOP"
    assert db.scalar(select(func.count()).select_from(PlaybookRun)
                     .where(PlaybookRun.case_id == case.case_id)) == 1
    assert db.scalar(select(func.count()).select_from(ScheduledJob)) == 1


# --- D. failure / retry semantics --------------------------------------------


def test_downstream_activation_failure_is_not_swallowed(db, make_case, bound):
    """No catalog seeded -> activate_case raises PlaybookNotFoundError for a
    root cause that DOES have a catalog entry. The chain must propagate this,
    not report success."""
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value,
        diagnosis_confidence=0.9, context={"gateway": "razorpay"},
    )
    # diagnose the case for real, driving it to PLAYBOOK_ACTIVE, without a
    # seeded catalog:
    from torque.exceptions import PlaybookNotFoundError
    from torque.policy.tasks import activate_case_task

    case.status = CaseStatus.PLAYBOOK_ACTIVE
    db.flush()
    with pytest.raises(PlaybookNotFoundError):
        activate_case_task(str(case.case_id))


def test_ingestion_dispatch_never_advances_case_status(db, make_merchant, monkeypatch, bound):
    """Recording the ready case id (Module 12a's `on_case_ready`) must never, by
    itself, change anything about the case — the dispatch happens outside any
    engine write path."""
    m = make_merchant()
    monkeypatch.setattr("torque.ingestion.tasks.dispatch_diagnosis", lambda cid: None)
    ev = _event(db, m, type_="payment.failed", key="pf_status",
               payload=_pf_payload(payment_id="pay_s", order_id="ord_s", contact="+919999000005"))

    resolve_buffered_event_task(str(ev.event_id))

    case = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()
    assert case.status is CaseStatus.DETECTED  # unchanged by the dispatch itself


# --- E. end-to-end: no manual engine call ------------------------------------


def test_end_to_end_ingestion_to_scheduled_execution(db, make_merchant, bound):
    """One webhook-shaped Event in -> the case comes out the other end with a
    PlaybookRun and an armed ScheduledJob, entirely via the task chain."""
    m = make_merchant()
    seed_catalog(db)
    ev = _event(db, m, type_="payment.failed", key="pf_e2e",
               payload=_pf_payload(payment_id="pay_e2e", order_id="ord_e2e",
                                   contact="+919999000006", error_code="insufficient_funds"))

    resolve_buffered_event_task(str(ev.event_id))

    case = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE
    assert case.root_cause_code is not None
    run = db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).one()
    assert db.scalars(select(ScheduledJob).where(ScheduledJob.run_id == run.run_id)).one()


def test_end_to_end_low_confidence_escalates_without_a_run(db, make_merchant, bound):
    m = make_merchant()
    seed_catalog(db)
    ev = _event(db, m, type_="payment.failed", key="pf_esc",
               payload=_pf_payload(payment_id="pay_esc", order_id="ord_esc",
                                   contact="+919999000007", error_code="UNKNOWN_XYZ"))

    resolve_buffered_event_task(str(ev.event_id))

    case = db.scalars(
        select(RevenueLeakCase).where(RevenueLeakCase.merchant_id == m.merchant_id)
    ).one()
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN
    assert db.scalar(select(func.count()).select_from(PlaybookRun)
                     .where(PlaybookRun.case_id == case.case_id)) == 0


# --- F. demo scenarios: the dispatch=True wiring (Module 12a / B1) ----------


def test_demo_inject_dispatches_diagnosis_via_the_api(make_api_client):
    """`POST /demo/inject/{key}` opts in to dispatch (`torque.api.demo.
    post_inject` passes `dispatch=True`) — proves the wiring end to end at the
    HTTP layer, spied exactly like the other ingestion enqueues."""
    client = make_api_client()
    client.post("/demo/seed")

    r = client.post("/demo/inject/payment_failure")
    assert r.status_code == 200
    client.diagnose_enqueue.assert_called_once()
    (args, _kwargs) = client.diagnose_enqueue.call_args
    assert args[0] == (r.json()["case_id"],)


def test_demo_inject_direct_call_does_not_dispatch_by_default(db):
    """The bare function (used throughout the Module 10 demo test suite) must
    stay side-effect-free by default — `dispatch` defaults to `False`."""
    from torque.demo import seed_demo
    from torque.demo.scenarios import inject_scenario

    seed_demo(db)
    # No monkeypatch, no celery_eager, no broker: if this tried to dispatch,
    # it would hang/raise. It must not.
    out = inject_scenario(db, "payment_failure")
    assert out["status"] == "DETECTED"


def test_demo_cross_leg_and_b2b_scenarios_dispatch_via_the_api(make_api_client):
    client = make_api_client()
    client.post("/demo/seed")

    merge = client.post("/demo/inject/cross_leg_merge")
    assert merge.status_code == 200
    bundle = client.post("/demo/inject/b2b_invoice_bundle")
    assert bundle.status_code == 200

    assert client.diagnose_enqueue.call_count == 2
    dispatched_ids = {c.args[0] for c in client.diagnose_enqueue.call_args_list}
    assert dispatched_ids == {(merge.json()["case_id"],), (bundle.json()["case_id"],)}
