"""Blueprint Section 3 - NACHRetryPolicy: self-imposed ceiling + batch-clearing
gate as a pure predicate; schema invariants."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from torque.compliance import nach_retry_eligible
from torque.config import get_policy
from torque.db.scoped import TenantScope
from torque.enums import ClearingCycleStatus
from torque.models import NACHRetryPolicy

TODAY = date(2026, 9, 1)
CEILING = get_policy().nach_representment_ceiling_default  # 3


def test_eligible_when_returned_under_ceiling_and_window_open():
    assert nach_retry_eligible(
        clearing_cycle_status=ClearingCycleStatus.RETURNED,
        dishonour_count_this_fy=2,
        retry_eligible_after=None,
        ceiling=CEILING,
        as_of=TODAY,
    )


def test_not_eligible_when_pending_clearing():
    assert not nach_retry_eligible(
        clearing_cycle_status=ClearingCycleStatus.PENDING_CLEARING,
        dishonour_count_this_fy=0,
        retry_eligible_after=None,
        ceiling=CEILING,
        as_of=TODAY,
    )


def test_not_eligible_when_cleared():
    assert not nach_retry_eligible(
        clearing_cycle_status=ClearingCycleStatus.CLEARED,
        dishonour_count_this_fy=0,
        retry_eligible_after=None,
        ceiling=CEILING,
        as_of=TODAY,
    )


def test_not_eligible_at_ceiling():
    assert not nach_retry_eligible(
        clearing_cycle_status=ClearingCycleStatus.RETURNED,
        dishonour_count_this_fy=CEILING,
        retry_eligible_after=None,
        ceiling=CEILING,
        as_of=TODAY,
    )


def test_not_eligible_before_batch_window():
    assert not nach_retry_eligible(
        clearing_cycle_status=ClearingCycleStatus.RETURNED,
        dishonour_count_this_fy=1,
        retry_eligible_after=TODAY + timedelta(days=3),
        ceiling=CEILING,
        as_of=TODAY,
    )


def test_eligible_on_or_after_batch_window():
    assert nach_retry_eligible(
        clearing_cycle_status=ClearingCycleStatus.RETURNED,
        dishonour_count_this_fy=1,
        retry_eligible_after=TODAY,
        ceiling=CEILING,
        as_of=TODAY,
    )


# --- schema ----------------------------------------------------------


def test_clearing_cycle_status_enum_enforced(db, make_merchant):
    m = make_merchant()
    from sqlalchemy import text

    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO nach_retry_policy "
                "(merchant_id, mandate_id, clearing_cycle_status) "
                "VALUES (:m, 'mand_x', 'NOT_A_STATUS')"
            ),
            {"m": m.merchant_id},
        )


def test_dishonour_count_non_negative(db, make_merchant):
    m = make_merchant()
    db.add(
        NACHRetryPolicy(
            merchant_id=m.merchant_id,
            mandate_id="mand_neg",
            clearing_cycle_status=ClearingCycleStatus.RETURNED,
            dishonour_count_this_fy=-1,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_tenant_scoped(db, make_merchant):
    m = make_merchant()
    scope = TenantScope(db, m.merchant_id)
    policy = NACHRetryPolicy(
        mandate_id="mand_scoped",
        clearing_cycle_status=ClearingCycleStatus.PENDING_CLEARING,
    )
    scope.add(policy)
    db.flush()
    assert policy.merchant_id == m.merchant_id
