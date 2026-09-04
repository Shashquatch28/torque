"""Module 9 §9.4 — batch reporting over an `opened_at` window: complete, mixed,
empty, and partially-processed batches; half-open date boundaries; and query
idempotency (repeated reads are byte-identical, no persisted aggregate to
double-count — D-114).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tests.module9_helpers import set_recovery, set_status
from torque.enums import CaseStatus, LegType, RecoveryType
from torque.reporting import metrics
from torque.reporting.metrics import ReportWindow

_A = RecoveryType.AGENT_ASSISTED
_BATCH_START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def _case(make_case, m, *, amount, opened_at, **kw):
    return make_case(
        merchant=m, leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
        amount_at_risk=Decimal(str(amount)), opened_at=opened_at, **kw,
    )


def test_empty_batch_window(db, make_merchant, make_case):
    m = make_merchant()
    _case(make_case, m, amount="1000.00", opened_at=datetime(2026, 8, 1, tzinfo=UTC))
    rep = metrics.recovery_report(
        db, m.merchant_id,
        window=ReportWindow(start=_BATCH_START, end=_BATCH_START + timedelta(days=30)),
    )
    assert rep.summary.case_count == 0
    assert rep.summary.revenue_at_risk == Decimal("0.00")
    assert rep.by_leg == []
    assert rep.operational.blocked_by_reason == []


def test_complete_batch_all_recovered(db, make_merchant, make_case):
    m = make_merchant()
    for i in range(4):
        c = _case(make_case, m, amount="1000.00",
                  opened_at=_BATCH_START + timedelta(days=i))
        set_recovery(db, c, recovery_type=_A, amount="1000.00")
    rep = metrics.recovery_report(
        db, m.merchant_id,
        window=ReportWindow(start=_BATCH_START, end=_BATCH_START + timedelta(days=30)),
    )
    assert rep.summary.case_count == 4
    assert rep.summary.recovered_case_count == 4
    assert rep.summary.recovered_amount == Decimal("4000.00")
    assert rep.summary.recovery_rate == Decimal("1.0000")


def test_mixed_outcome_batch(db, make_merchant, make_case):
    m = make_merchant()
    rec = _case(make_case, m, amount="10000.00", opened_at=_BATCH_START)
    slf = _case(make_case, m, amount="5000.00", opened_at=_BATCH_START + timedelta(days=1))
    exhausted = _case(make_case, m, amount="3000.00", opened_at=_BATCH_START + timedelta(days=2))
    _open = _case(make_case, m, amount="2000.00", opened_at=_BATCH_START + timedelta(days=3))
    set_recovery(db, rec, recovery_type=_A, amount="10000.00")
    set_recovery(db, slf, recovery_type=RecoveryType.SELF_RECOVERED, amount="5000.00",
                 status=CaseStatus.CANCELLED)
    set_status(db, exhausted, CaseStatus.EXHAUSTED)

    rep = metrics.recovery_report(
        db, m.merchant_id,
        window=ReportWindow(start=_BATCH_START, end=_BATCH_START + timedelta(days=30)),
    )
    s = rep.summary
    assert s.case_count == 4
    assert s.revenue_at_risk == Decimal("20000.00")
    assert s.recovered_amount == Decimal("10000.00")
    assert s.self_recovered_amount == Decimal("5000.00")
    assert s.unresolved_case_count == 2  # exhausted + open
    assert s.unresolved_amount == Decimal("5000.00")
    assert s.recovery_rate == Decimal("0.2500")  # 1 of 4
    assert _open.status is CaseStatus.DETECTED


def test_partially_processed_batch_only_counts_current_state(db, make_merchant, make_case):
    """A batch mid-flight: some cases still DIAGNOSING / PLAYBOOK_ACTIVE. The
    report shows them as unresolved now, not as failures."""
    m = make_merchant()
    done = _case(make_case, m, amount="1000.00", opened_at=_BATCH_START)
    diagnosing = _case(make_case, m, amount="2000.00", opened_at=_BATCH_START,
                       status=CaseStatus.DIAGNOSING)
    active = _case(make_case, m, amount="3000.00", opened_at=_BATCH_START,
                   status=CaseStatus.PLAYBOOK_ACTIVE)
    set_recovery(db, done, recovery_type=_A, amount="1000.00")

    s = metrics.recovery_summary(
        db, m.merchant_id, window=ReportWindow(start=_BATCH_START),
    )
    assert s.case_count == 3
    assert s.recovered_case_count == 1
    assert s.unresolved_case_count == 2
    assert s.unresolved_amount == Decimal("5000.00")
    assert diagnosing.status is CaseStatus.DIAGNOSING
    assert active.status is CaseStatus.PLAYBOOK_ACTIVE


def test_batch_window_is_half_open_on_opened_at(db, make_merchant, make_case):
    m = make_merchant()
    boundary = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)
    _case(make_case, m, amount="1000.00", opened_at=boundary - timedelta(seconds=1))
    _case(make_case, m, amount="2000.00", opened_at=boundary)
    _case(make_case, m, amount="4000.00", opened_at=boundary + timedelta(days=1))

    left = metrics.recovery_summary(db, m.merchant_id, window=ReportWindow(end=boundary))
    right = metrics.recovery_summary(db, m.merchant_id, window=ReportWindow(start=boundary))
    assert left.case_count == 1 and left.revenue_at_risk == Decimal("1000.00")
    assert right.case_count == 2 and right.revenue_at_risk == Decimal("6000.00")
    # the two windows partition the cases exactly, no overlap
    assert left.case_count + right.case_count == 3


def test_naive_window_bounds_treated_as_utc(db, make_merchant, make_case):
    m = make_merchant()
    _case(make_case, m, amount="1000.00", opened_at=datetime(2026, 9, 10, 12, 0, tzinfo=UTC))
    aware = metrics.recovery_summary(
        db, m.merchant_id,
        window=ReportWindow(start=datetime(2026, 9, 10, 0, 0, tzinfo=UTC)),
    )
    naive = metrics.recovery_summary(
        db, m.merchant_id, window=ReportWindow(start=datetime(2026, 9, 10, 0, 0)),
    )
    assert aware.case_count == naive.case_count == 1


def test_repeated_queries_are_identical(db, make_merchant, make_case):
    m = make_merchant()
    for i in range(3):
        c = _case(make_case, m, amount="1000.00", opened_at=_BATCH_START + timedelta(days=i))
        set_recovery(db, c, recovery_type=_A, amount="1000.00",
                     closed_at=_BATCH_START + timedelta(days=i, hours=5))
    a = metrics.recovery_report(db, m.merchant_id)
    b = metrics.recovery_report(db, m.merchant_id)
    assert a.model_dump() == b.model_dump()
    ta = metrics.recovery_over_time(db, m.merchant_id, bucket="day")
    tb = metrics.recovery_over_time(db, m.merchant_id, bucket="day")
    assert [x.model_dump() for x in ta] == [x.model_dump() for x in tb]


def test_over_time_windows_partition_without_double_count(db, make_merchant, make_case):
    m = make_merchant()
    mid = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    for day, amt in ((datetime(2026, 9, 8, tzinfo=UTC), "1000.00"),
                     (datetime(2026, 9, 9, 23, 59, tzinfo=UTC), "2000.00"),
                     (mid, "4000.00"),
                     (datetime(2026, 9, 12, tzinfo=UTC), "8000.00")):
        c = _case(make_case, m, amount=amt, opened_at=datetime(2026, 9, 1, tzinfo=UTC))
        set_recovery(db, c, recovery_type=_A, amount=amt, closed_at=day)

    first = metrics.recovery_over_time(db, m.merchant_id, window=ReportWindow(end=mid))
    second = metrics.recovery_over_time(db, m.merchant_id, window=ReportWindow(start=mid))
    total = sum(b.recovered_amount for b in first) + sum(b.recovered_amount for b in second)
    assert sum(b.recovered_amount for b in first) == Decimal("3000.00")
    assert sum(b.recovered_amount for b in second) == Decimal("12000.00")
    assert total == Decimal("15000.00")
