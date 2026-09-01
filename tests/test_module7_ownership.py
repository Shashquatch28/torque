"""Blueprint Section 3 — `recovery_type` and `recovered_amount` are written
ONLY by Module 7. The guard rejects any write outside `module7_writer`."""

from __future__ import annotations

import pytest

from torque.enums import LegType, RecoveryType
from torque.exceptions import OwnershipViolation
from torque.models import RevenueLeakCase
from torque.models.guards import module7_writer


@pytest.fixture()
def case(db, make_merchant, make_counterparty, make_event):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    c = RevenueLeakCase(
        merchant_id=m.merchant_id,
        leg_type=LegType.PAYMENT_DEGRADATION,
        source_event_id=ev.event_id,
        counterparty_id=cp.counterparty_id,
        amount_at_risk=1000,
        context={"gateway": "razorpay"},
    )
    db.add(c)
    db.flush()
    return c


def test_direct_write_to_recovery_type_rejected(db, case):
    case.recovery_type = RecoveryType.AGENT_ASSISTED
    with pytest.raises(OwnershipViolation):
        db.flush()


def test_direct_write_to_recovered_amount_rejected(db, case):
    case.recovered_amount = 999
    with pytest.raises(OwnershipViolation):
        db.flush()


def test_write_allowed_inside_module7_writer(db, case):
    with module7_writer(db):
        case.recovery_type = RecoveryType.AGENT_ASSISTED
        case.recovered_amount = 1000
        db.flush()
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED
    assert int(case.recovered_amount) == 1000
