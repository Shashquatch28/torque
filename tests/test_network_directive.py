"""Blueprint Section 3 / Section 4 — network_directive records the MOST
restrictive tier ever received and never downgrades; it is writable only via
`apply_network_directive`."""

from __future__ import annotations

import pytest

from torque.enums import LegType, MacTier
from torque.exceptions import MonotonicityViolation, OwnershipViolation
from torque.models import RevenueLeakCase
from torque.state_machine import apply_network_directive


def _case(db, m, cp, ev):
    case = RevenueLeakCase(
        merchant_id=m.merchant_id,
        leg_type=LegType.PAYMENT_DEGRADATION,
        source_event_id=ev.event_id,
        counterparty_id=cp.counterparty_id,
        amount_at_risk=1000,
        context={"gateway": "razorpay"},
    )
    db.add(case)
    db.flush()
    return case


def test_apply_then_escalate_to_more_restrictive(db, make_merchant, make_counterparty, make_event):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    case = _case(db, m, cp, ev)

    apply_network_directive(db, case, mac_code="5C", tier=MacTier.TIER_2_CAPPED_RETRY)
    assert case.network_directive_tier is MacTier.TIER_2_CAPPED_RETRY

    apply_network_directive(db, case, mac_code="03", tier=MacTier.TIER_1_HARD_STOP)
    assert case.network_directive_tier is MacTier.TIER_1_HARD_STOP
    assert case.network_directive_mac_code == "03"


def test_downgrade_is_rejected(db, make_merchant, make_counterparty, make_event):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    case = _case(db, m, cp, ev)
    apply_network_directive(db, case, mac_code="03", tier=MacTier.TIER_1_HARD_STOP)
    with pytest.raises(MonotonicityViolation):
        apply_network_directive(db, case, mac_code="24", tier=MacTier.TIMED_RETRY)


def test_tier3_does_not_downgrade_to_tier2(db, make_merchant, make_counterparty, make_event):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    case = _case(db, m, cp, ev)
    apply_network_directive(db, case, mac_code="40", tier=MacTier.TIER_3_INSTRUMENT_DEAD)
    with pytest.raises(MonotonicityViolation):
        apply_network_directive(db, case, mac_code="5C", tier=MacTier.TIER_2_CAPPED_RETRY)


def test_direct_write_without_helper_is_rejected(
    db, make_merchant, make_counterparty, make_event
):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    case = _case(db, m, cp, ev)
    case.network_directive_tier = MacTier.TIER_1_HARD_STOP
    with pytest.raises(OwnershipViolation):
        db.flush()
