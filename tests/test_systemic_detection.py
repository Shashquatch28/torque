"""Milestone 7c — systemic detection & suppression (Blueprint §2.5, NETWORK_WIDE).

Direct tests of `torque.ingestion.systemic.run_systemic_detection` and the §2.7
ingestion hook against the harness session. The Celery hop is exercised in the
eager end-to-end test at the bottom.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.enums import CaseEventType, CaseStatus, SystemicScope
from torque.ingestion.buffer import resolve_buffered_event
from torque.ingestion.systemic import run_systemic_detection
from torque.models import (
    CardRetryBudget,
    CaseEvent,
    RevenueLeakCase,
    SystemicEvent,
    UPIRetryBudget,
)


def _systemic_events(db, merchant_id):
    return list(
        db.scalars(select(SystemicEvent).where(SystemicEvent.merchant_id == merchant_id))
    )


def _active(db, merchant_id):
    return list(
        db.scalars(
            select(SystemicEvent)
            .where(SystemicEvent.merchant_id == merchant_id)
            .where(SystemicEvent.resolved_at.is_(None))
        )
    )


def _case_events(db, case_id, event_type):
    return list(
        db.scalars(
            select(CaseEvent)
            .where(CaseEvent.case_id == case_id)
            .where(CaseEvent.event_type == event_type)
        )
    )


# --- detection: threshold conditions ---------------------------------------


def test_qualifying_spike_creates_one_network_wide_event(
    db, make_merchant, make_case, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)  # baseline
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)      # window
    make_case(merchant=m)  # one DETECTED case

    run_systemic_detection(db, now=datetime.now(UTC))

    events = _systemic_events(db, m.merchant_id)
    assert len(events) == 1
    se = events[0]
    assert se.scope is SystemicScope.NETWORK_WIDE
    assert se.issuer_code is None and se.network is None
    assert se.resolved_at is None
    assert se.failure_rate_at_detection > 0
    assert se.affected_case_count == 1


def test_below_absolute_count_floor_does_not_trip(
    db, make_merchant, make_failure_events, systemic_policy
):
    systemic_policy(systemic_absolute_count_floor=5)
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=4, start_minutes_ago=9, end_minutes_ago=1)  # 4 < M=5

    run_systemic_detection(db, now=datetime.now(UTC))
    assert _systemic_events(db, m.merchant_id) == []


def test_absolute_count_floor_boundary_trips(
    db, make_merchant, make_failure_events, systemic_policy
):
    systemic_policy(systemic_absolute_count_floor=5)
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=5, start_minutes_ago=9, end_minutes_ago=1)  # 5 == M

    run_systemic_detection(db, now=datetime.now(UTC))
    assert len(_systemic_events(db, m.merchant_id)) == 1


def test_below_baseline_floor_does_not_trip(
    db, make_merchant, make_failure_events, systemic_policy
):
    systemic_policy(systemic_baseline_floor_per_min=0.01)
    m = make_merchant()
    # 14 / 1430 min ~= 0.0098 /min  <  N = 0.01
    make_failure_events(m, count=14, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)

    run_systemic_detection(db, now=datetime.now(UTC))
    assert _systemic_events(db, m.merchant_id) == []


def test_baseline_floor_boundary_trips(
    db, make_merchant, make_failure_events, systemic_policy
):
    systemic_policy(systemic_baseline_floor_per_min=0.01)
    m = make_merchant()
    # 15 / 1430 min ~= 0.0105 /min  >=  N = 0.01
    make_failure_events(m, count=15, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)

    run_systemic_detection(db, now=datetime.now(UTC))
    assert len(_systemic_events(db, m.merchant_id)) == 1


def test_below_spike_multiplier_does_not_trip(
    db, make_merchant, make_failure_events, systemic_policy
):
    systemic_policy(systemic_absolute_count_floor=3, systemic_baseline_floor_per_min=0.05)
    m = make_merchant()
    make_failure_events(m, count=143, start_minutes_ago=1400, end_minutes_ago=20)  # ~0.1/min
    make_failure_events(m, count=4, start_minutes_ago=9, end_minutes_ago=1)        # 0.4 < 5*0.1

    run_systemic_detection(db, now=datetime.now(UTC))
    assert _systemic_events(db, m.merchant_id) == []


def test_spike_multiplier_boundary_trips(
    db, make_merchant, make_failure_events, systemic_policy
):
    systemic_policy(systemic_absolute_count_floor=3, systemic_baseline_floor_per_min=0.05)
    m = make_merchant()
    make_failure_events(m, count=143, start_minutes_ago=1400, end_minutes_ago=20)  # ~0.1/min
    make_failure_events(m, count=5, start_minutes_ago=9, end_minutes_ago=1)        # 0.5 == 5*0.1

    run_systemic_detection(db, now=datetime.now(UTC))
    assert len(_systemic_events(db, m.merchant_id)) == 1


def test_baseline_excludes_the_live_detection_window(
    db, make_merchant, make_failure_events, systemic_policy
):
    from torque.ingestion.systemic import _baseline_failure_rate

    systemic_policy()
    m = make_merchant()
    now = datetime.now(UTC)
    make_failure_events(m, count=30, start_minutes_ago=9, end_minutes_ago=1)       # in window
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)   # in baseline

    rate = _baseline_failure_rate(db, merchant_id=m.merchant_id, now=now)
    # only the 20 older events count — not 50
    assert abs(rate - 20 / 1430) < 1e-9


# --- detection: multi-merchant / tenant isolation -------------------------


def test_one_merchant_spike_does_not_touch_another(
    db, make_merchant, make_case, make_failure_events, systemic_policy
):
    systemic_policy()
    a, b = make_merchant(), make_merchant()
    make_failure_events(a, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(a, count=10, start_minutes_ago=9, end_minutes_ago=1)
    case_a = make_case(merchant=a)
    case_b = make_case(merchant=b)  # merchant B: no failures at all

    run_systemic_detection(db, now=datetime.now(UTC))

    assert len(_systemic_events(db, a.merchant_id)) == 1
    assert _systemic_events(db, b.merchant_id) == []
    db.refresh(case_a)
    db.refresh(case_b)
    assert case_a.status is CaseStatus.SYSTEMIC_HOLD
    assert case_b.status is CaseStatus.DETECTED
    assert case_b.systemic_event_id is None


def test_no_duplicate_active_event_on_repeated_run(
    db, make_merchant, make_case, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    make_case(merchant=m)
    now = datetime.now(UTC)

    run_systemic_detection(db, now=now)
    run_systemic_detection(db, now=now)

    assert len(_active(db, m.merchant_id)) == 1
    assert len(_systemic_events(db, m.merchant_id)) == 1


# --- case sweep --------------------------------------------------------------


def test_detected_case_is_swept_with_full_audit(
    db, make_merchant, make_case, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    case = make_case(merchant=m)

    run_systemic_detection(db, now=datetime.now(UTC))

    db.refresh(case)
    (se,) = _systemic_events(db, m.merchant_id)
    assert case.status is CaseStatus.SYSTEMIC_HOLD
    assert case.systemic_event_id == se.systemic_event_id

    status_events = _case_events(db, case.case_id, CaseEventType.STATUS_CHANGED)
    assert any(
        e.payload["to_status"] == CaseStatus.SYSTEMIC_HOLD.value
        and e.payload["trigger"] == "systemic_network_wide"
        for e in status_events
    )
    (hold_ev,) = _case_events(db, case.case_id, CaseEventType.SYSTEMIC_HOLD_APPLIED)
    assert hold_ev.payload["systemic_event_id"] == str(se.systemic_event_id)
    assert hold_ev.payload["scope"] == SystemicScope.NETWORK_WIDE.value
    assert hold_ev.payload["issuer_code"] is None


def test_affected_case_count_matches_held_cases(
    db, make_merchant, make_case, make_counterparty, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    cp = make_counterparty()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    for _ in range(3):
        make_case(merchant=m, counterparty=cp)

    run_systemic_detection(db, now=datetime.now(UTC))

    (se,) = _systemic_events(db, m.merchant_id)
    assert se.affected_case_count == 3
    held = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
        .where(RevenueLeakCase.status == CaseStatus.SYSTEMIC_HOLD)
    ).all()
    assert len(held) == 3


def test_non_detected_case_is_not_swept(
    db, make_merchant, make_case, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    case = make_case(merchant=m)
    case.status = CaseStatus.DIAGNOSING  # raw set — not reachable via the app yet
    db.flush()

    run_systemic_detection(db, now=datetime.now(UTC))

    db.refresh(case)
    assert case.status is CaseStatus.DIAGNOSING
    assert case.systemic_event_id is None


def test_repeated_run_does_not_double_hold_or_double_audit(
    db, make_merchant, make_case, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    case = make_case(merchant=m)
    now = datetime.now(UTC)

    run_systemic_detection(db, now=now)
    run_systemic_detection(db, now=now)

    assert len(_case_events(db, case.case_id, CaseEventType.SYSTEMIC_HOLD_APPLIED)) == 1
    assert len(_case_events(db, case.case_id, CaseEventType.STATUS_CHANGED)) == 1


# --- §2.7 ingestion hook ---------------------------------------------------


def _run_buffer_for_new_failure(db, make_event, merchant, **body):
    ev = make_event(
        merchant,
        type="payment.failed",
        raw_payload=json.loads(razorpay_payment_body(event="payment.failed", **body)),
    )
    resolve_buffered_event(db, event_id=ev.event_id)
    return db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == merchant.merchant_id)
        .where(RevenueLeakCase.source_event_id == ev.event_id)
    ).one()


def test_case_created_during_active_event_is_born_held(
    db, make_merchant, make_event, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    run_systemic_detection(db, now=datetime.now(UTC))
    (se,) = _systemic_events(db, m.merchant_id)

    case = _run_buffer_for_new_failure(
        db, make_event, m, payment_id="pay_new", order_id="order_new"
    )
    assert case.status is CaseStatus.SYSTEMIC_HOLD
    assert case.systemic_event_id == se.systemic_event_id
    assert len(_case_events(db, case.case_id, CaseEventType.SYSTEMIC_HOLD_APPLIED)) == 1


def test_case_created_without_active_event_stays_detected(db, make_merchant, make_event):
    m = make_merchant()
    case = _run_buffer_for_new_failure(db, make_event, m, payment_id="pay_x", order_id="order_x")
    assert case.status is CaseStatus.DETECTED
    assert case.systemic_event_id is None


def test_hook_does_not_disturb_card_budget_or_event_processed(
    db, make_merchant, make_event, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    run_systemic_detection(db, now=datetime.now(UTC))

    ev = make_event(
        m,
        type="payment.failed",
        raw_payload=json.loads(
            razorpay_payment_body(event="payment.failed", method="card", token_id="tok_held")
        ),
    )
    resolve_buffered_event(db, event_id=ev.event_id)

    db.refresh(ev)
    assert ev.processed is True
    budgets = db.scalars(
        select(CardRetryBudget).where(CardRetryBudget.merchant_id == m.merchant_id)
    ).all()
    assert len(budgets) == 1 and budgets[0].attempts_used_24h == 1


# --- resolution ----------------------------------------------------------


def _trip(db, m, make_case, make_failure_events, systemic_policy, *, now):
    systemic_policy()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    case = make_case(merchant=m)
    run_systemic_detection(db, now=now)
    return case


def test_event_stays_active_while_failures_persist(
    db, make_merchant, make_case, make_failure_events, systemic_policy
):
    m = make_merchant()
    now = datetime.now(UTC)
    case = _trip(db, m, make_case, make_failure_events, systemic_policy, now=now)

    run_systemic_detection(db, now=now + timedelta(minutes=1))  # window still hot

    assert len(_active(db, m.merchant_id)) == 1
    db.refresh(case)
    assert case.status is CaseStatus.SYSTEMIC_HOLD


def test_resolution_after_sustained_quiet_requeues_to_diagnosing(
    db, make_merchant, make_case, make_failure_events, systemic_policy
):
    m = make_merchant()
    now = datetime.now(UTC)
    case = _trip(db, m, make_case, make_failure_events, systemic_policy, now=now)
    (se,) = _systemic_events(db, m.merchant_id)

    run_systemic_detection(db, now=now + timedelta(minutes=30))  # no failures in last 10 min

    db.refresh(se)
    db.refresh(case)
    assert se.resolved_at is not None
    assert case.status is CaseStatus.DIAGNOSING
    assert case.systemic_event_id == se.systemic_event_id  # FK left set (audit)


def test_resolution_only_touches_its_own_held_cases(
    db, make_merchant, make_case, make_counterparty, make_failure_events, systemic_policy
):
    m = make_merchant()
    now = datetime.now(UTC)
    systemic_policy()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    held = make_case(merchant=m)
    run_systemic_detection(db, now=now)
    (se,) = _systemic_events(db, m.merchant_id)

    # an unrelated SYSTEMIC_HOLD case NOT linked to this event
    stray = make_case(merchant=m, counterparty=make_counterparty())
    stray.status = CaseStatus.SYSTEMIC_HOLD
    db.flush()

    run_systemic_detection(db, now=now + timedelta(minutes=30))

    db.refresh(held)
    db.refresh(stray)
    assert held.status is CaseStatus.DIAGNOSING
    assert stray.status is CaseStatus.SYSTEMIC_HOLD  # untouched — no systemic_event_id


def test_repeated_resolution_run_is_idempotent(
    db, make_merchant, make_case, make_failure_events, systemic_policy
):
    m = make_merchant()
    now = datetime.now(UTC)
    case = _trip(db, m, make_case, make_failure_events, systemic_policy, now=now)
    (se,) = _systemic_events(db, m.merchant_id)

    run_systemic_detection(db, now=now + timedelta(minutes=30))
    first_resolved_at = se.resolved_at
    run_systemic_detection(db, now=now + timedelta(minutes=45))

    db.refresh(se)
    db.refresh(case)
    assert se.resolved_at == first_resolved_at
    assert case.status is CaseStatus.DIAGNOSING
    assert len(_case_events(db, case.case_id, CaseEventType.STATUS_CHANGED)) == 2  # hold + resume


# --- retry-rail boundary ------------------------------------------------


def test_systemic_processing_never_creates_a_upi_retry_budget(
    db, make_merchant, make_case, make_event, make_failure_events, systemic_policy
):
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    make_case(merchant=m)
    run_systemic_detection(db, now=datetime.now(UTC))
    _run_buffer_for_new_failure(db, make_event, m, payment_id="pay_u", order_id="order_u")

    assert db.scalars(select(UPIRetryBudget)).all() == []


# --- transactional atomicity -----------------------------------------------


def test_failure_mid_sweep_rolls_everything_back(
    db,
    make_merchant,
    make_case,
    make_counterparty,
    make_failure_events,
    systemic_policy,
    monkeypatch,
):
    systemic_policy()
    m = make_merchant()
    cp = make_counterparty()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    for _ in range(3):
        make_case(merchant=m, counterparty=cp)

    calls = {"n": 0}
    import torque.ingestion.systemic as sysmod

    real_hold = sysmod._hold_case

    def _boom(session, *, case, systemic_event):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("sweep failed")
        return real_hold(session, case=case, systemic_event=systemic_event)

    monkeypatch.setattr(sysmod, "_hold_case", _boom)

    savepoint = db.begin_nested()
    try:
        run_systemic_detection(db, now=datetime.now(UTC))
    except RuntimeError:
        pass
    savepoint.rollback()

    assert _systemic_events(db, m.merchant_id) == []
    still_detected = db.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == m.merchant_id)
        .where(RevenueLeakCase.status == CaseStatus.DETECTED)
    ).all()
    assert len(still_detected) == 3


# --- eager end-to-end ----------------------------------------------------


def test_eager_task_detects_and_holds(
    db, make_merchant, make_case, make_failure_events, systemic_policy, celery_eager, monkeypatch
):
    from contextlib import contextmanager

    import torque.ingestion.tasks as tasks_mod
    from torque.ingestion.tasks import detect_systemic_task

    @contextmanager
    def _fake_scope():
        yield db

    monkeypatch.setattr(tasks_mod, "_session_scope", _fake_scope)
    systemic_policy()
    m = make_merchant()
    make_failure_events(m, count=20, start_minutes_ago=1400, end_minutes_ago=20)
    make_failure_events(m, count=10, start_minutes_ago=9, end_minutes_ago=1)
    case = make_case(merchant=m)

    detect_systemic_task.apply_async()  # eager → runs inline against `db` (uses real now())

    db.refresh(case)
    assert case.status is CaseStatus.SYSTEMIC_HOLD
    assert len(_active(db, m.merchant_id)) == 1
