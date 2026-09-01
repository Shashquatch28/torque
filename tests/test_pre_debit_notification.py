"""Blueprint Section 3 / Module 6 guardrail - PreDebitNotification: the >=24h,
per-attempt EXISTS check as a pure predicate; schema invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from torque.compliance import PRE_DEBIT_MIN_GAP_HOURS, gap_satisfied
from torque.db.scoped import TenantScope
from torque.models import PreDebitNotification

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _notify(db, case, *, hours_ago: float, attempt: int, amount="500.00"):
    row = PreDebitNotification(
        merchant_id=case.merchant_id,
        case_id=case.case_id,
        notified_at=NOW - timedelta(hours=hours_ago),
        covers_attempt_number=attempt,
        channel="whatsapp",
        notified_amount=Decimal(amount),
    )
    db.add(row)
    db.flush()
    return row


def test_gap_satisfied_when_25h_old(db, make_case):
    case = make_case()
    _notify(db, case, hours_ago=25, attempt=2)
    assert gap_satisfied(db, case_id=case.case_id, next_attempt_number=2, now=NOW)


def test_gap_not_satisfied_when_23h_old(db, make_case):
    case = make_case()
    _notify(db, case, hours_ago=23, attempt=2)
    assert not gap_satisfied(db, case_id=case.case_id, next_attempt_number=2, now=NOW)


def test_gap_satisfied_exactly_at_24h(db, make_case):
    case = make_case()
    _notify(db, case, hours_ago=PRE_DEBIT_MIN_GAP_HOURS, attempt=1)
    assert gap_satisfied(db, case_id=case.case_id, next_attempt_number=1, now=NOW)


def test_gap_not_satisfied_for_a_different_attempt_number(db, make_case):
    case = make_case()
    _notify(db, case, hours_ago=48, attempt=2)
    assert not gap_satisfied(db, case_id=case.case_id, next_attempt_number=3, now=NOW)


def test_gap_not_satisfied_when_no_notification(db, make_case):
    case = make_case()
    assert not gap_satisfied(db, case_id=case.case_id, next_attempt_number=1, now=NOW)


def test_notified_amount_may_differ_from_mandate_amount(db, make_case):
    case = make_case(amount_at_risk=1000)
    row = _notify(db, case, hours_ago=30, attempt=1, amount="742.50")
    db.refresh(row)
    assert row.notified_amount == Decimal("742.50")


def test_covers_attempt_number_must_be_at_least_1(db, make_case):
    case = make_case()
    db.add(
        PreDebitNotification(
            merchant_id=case.merchant_id,
            case_id=case.case_id,
            notified_at=NOW,
            covers_attempt_number=0,
            channel="sms",
            notified_amount=Decimal("100.00"),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_tenant_scoped(db, make_merchant, make_case):
    m = make_merchant()
    case = make_case(merchant=m)
    scope = TenantScope(db, m.merchant_id)
    row = PreDebitNotification(
        case_id=case.case_id,
        notified_at=NOW,
        covers_attempt_number=1,
        channel="email",
        notified_amount=Decimal("10.00"),
    )
    scope.add(row)
    db.flush()
    assert row.merchant_id == m.merchant_id
