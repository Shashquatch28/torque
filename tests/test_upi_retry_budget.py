"""Blueprint Section 3 - UPIRetryBudget: the two independent gates as pure
predicates + schema invariants (hard_cap locked at 3, unique per mandate,
tenant scoping, no permitted_execution_window column)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from torque.compliance import (
    IST,
    UPI_AUTOPAY_HARD_CAP,
    upi_attempt_gate_open,
    within_upi_execution_window,
)
from torque.db.scoped import TenantScope
from torque.models import UPIRetryBudget

# --- gate 1: attempt count -------------------------------------------


def test_attempt_gate_open_below_cap():
    assert upi_attempt_gate_open(attempts_used=2, mandate_cancelled_at=None)


def test_attempt_gate_closed_at_cap():
    assert not upi_attempt_gate_open(
        attempts_used=UPI_AUTOPAY_HARD_CAP, mandate_cancelled_at=None
    )


def test_attempt_gate_closed_when_mandate_cancelled():
    assert not upi_attempt_gate_open(
        attempts_used=0, mandate_cancelled_at=datetime(2026, 9, 1, tzinfo=UTC)
    )


# --- gate 2: execution window (closed intervals, decision 5) --------

NAIVE_CASES = [
    ("09:59", True),
    ("10:00", False),   # closed interval start
    ("11:30", False),
    ("13:00", False),   # closed interval end
    ("13:00:01", True),
    ("14:00", True),
    ("16:59", True),
    ("17:00", False),
    ("20:00", False),
    ("21:30", False),   # closed interval end
    ("21:30:01", True),
    ("22:00", True),
]


@pytest.mark.parametrize(("hhmm", "expected"), NAIVE_CASES)
def test_execution_window_naive_is_treated_as_ist(hhmm, expected):
    parts = [int(p) for p in hhmm.split(":")]
    while len(parts) < 3:
        parts.append(0)
    when = datetime(2026, 9, 1, *parts)  # naive -> assumed IST
    assert within_upi_execution_window(when) is expected


def test_execution_window_converts_aware_datetime_to_ist():
    # 07:00 UTC == 12:30 IST -> inside the 10:00-13:00 peak -> blocked.
    utc_noon_ist = datetime(2026, 9, 1, 7, 0, tzinfo=UTC)
    assert within_upi_execution_window(utc_noon_ist) is False
    # 09:00 UTC == 14:30 IST -> outside peak -> allowed.
    assert within_upi_execution_window(datetime(2026, 9, 1, 9, 0, tzinfo=UTC)) is True


def test_execution_window_aware_ist_boundary():
    at_1330_ist = datetime(2026, 9, 1, 13, 0, tzinfo=IST)
    assert within_upi_execution_window(at_1330_ist) is False


# --- schema invariants ---------------------------------------------


def test_hard_cap_defaults_to_3(db, make_merchant):
    m = make_merchant()
    b = UPIRetryBudget(merchant_id=m.merchant_id, mandate_id="mand_default")
    db.add(b)
    db.flush()
    db.refresh(b)
    assert b.hard_cap == 3


def test_hard_cap_rejects_non_3(db, make_merchant):
    m = make_merchant()
    # Raw INSERT executes immediately; the CHECK (hard_cap = 3) fires here.
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO upi_retry_budget (merchant_id, mandate_id, hard_cap) "
                "VALUES (:m, 'mand_bad', 4)"
            ),
            {"m": m.merchant_id},
        )


def test_unique_mandate_per_merchant(db, make_merchant):
    m = make_merchant()
    db.add(UPIRetryBudget(merchant_id=m.merchant_id, mandate_id="mand_u"))
    db.flush()
    db.add(UPIRetryBudget(merchant_id=m.merchant_id, mandate_id="mand_u"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_tenant_scoped(db, make_merchant):
    m = make_merchant()
    scope = TenantScope(db, m.merchant_id)
    b = UPIRetryBudget(mandate_id="mand_scoped")
    scope.add(b)
    db.flush()
    assert b.merchant_id == m.merchant_id


def test_no_permitted_execution_window_column(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("upi_retry_budget")}
    assert "permitted_execution_window" not in cols
