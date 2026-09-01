"""Blueprint Section 3 / Decision J - SystemicEvent: schema invariants, the
ISSUER_SPECIFIC coherence constraint, the wired revenue_leak_case FK, and the
two pure predicates. No detection job, no case transitions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from torque.compliance import systemic_resolved, systemic_threshold_breached
from torque.config import get_policy
from torque.db.scoped import TenantScope
from torque.enums import Network, SystemicScope
from torque.exceptions import CrossTenantWriteError
from torque.models import RevenueLeakCase, SystemicEvent

DETECTED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _event(m, **kw):
    return SystemicEvent(
        merchant_id=m.merchant_id,
        scope=kw.pop("scope", SystemicScope.NETWORK_WIDE),
        failure_rate_at_detection=kw.pop("failure_rate_at_detection", Decimal("12.5")),
        detected_at=kw.pop("detected_at", DETECTED_AT),
        **kw,
    )


# --- schema ---------------------------------------------------------------


def test_scope_enum_enforced(db, make_merchant):
    m = make_merchant()
    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO systemic_event "
                "(merchant_id, scope, failure_rate_at_detection, detected_at) "
                "VALUES (:m, 'BOGUS', 1.0, now())"
            ),
            {"m": m.merchant_id},
        )


def test_defaults(db, make_merchant):
    m = make_merchant()
    e = _event(m)
    db.add(e)
    db.flush()
    db.refresh(e)
    assert e.resolved_at is None
    assert e.affected_case_count == 0


def test_failure_rate_non_negative(db, make_merchant):
    m = make_merchant()
    db.add(_event(m, failure_rate_at_detection=Decimal("-0.5")))
    with pytest.raises(IntegrityError):
        db.flush()


def test_affected_case_count_non_negative(db, make_merchant):
    m = make_merchant()
    db.add(_event(m, affected_case_count=-1))
    with pytest.raises(IntegrityError):
        db.flush()


# --- ISSUER_SPECIFIC coherence (decision E) ---------------------------


def test_issuer_specific_requires_a_target(db, make_merchant):
    m = make_merchant()
    db.add(_event(m, scope=SystemicScope.ISSUER_SPECIFIC))  # issuer_code + network both null
    with pytest.raises(IntegrityError):
        db.flush()


def test_issuer_specific_with_issuer_code_ok(db, make_merchant):
    m = make_merchant()
    db.add(_event(m, scope=SystemicScope.ISSUER_SPECIFIC, issuer_code="HDFC0001"))
    db.flush()


def test_issuer_specific_with_network_ok(db, make_merchant):
    m = make_merchant()
    db.add(_event(m, scope=SystemicScope.ISSUER_SPECIFIC, network=Network.MASTERCARD))
    db.flush()


def test_network_wide_may_omit_both(db, make_merchant):
    m = make_merchant()
    db.add(_event(m, scope=SystemicScope.NETWORK_WIDE))
    db.flush()


# --- tenant scoping -------------------------------------------------


def test_tenant_scoped(db, make_merchant):
    m1, m2 = make_merchant(), make_merchant()
    scope1 = TenantScope(db, m1.merchant_id)
    e = SystemicEvent(
        scope=SystemicScope.NETWORK_WIDE,
        failure_rate_at_detection=Decimal("5"),
        detected_at=DETECTED_AT,
    )
    scope1.add(e)
    db.flush()
    assert e.merchant_id == m1.merchant_id

    scope2 = TenantScope(db, m2.merchant_id)
    with pytest.raises(CrossTenantWriteError):
        scope2.add(_event(m1))


# --- wired FK on revenue_leak_case.systemic_event_id ----------------


def test_case_fk_accepts_a_real_event(db, make_case):
    case = make_case()
    e = SystemicEvent(
        merchant_id=case.merchant_id,
        scope=SystemicScope.NETWORK_WIDE,
        failure_rate_at_detection=Decimal("8"),
        detected_at=DETECTED_AT,
    )
    db.add(e)
    db.flush()
    case.systemic_event_id = e.systemic_event_id
    db.flush()
    assert db.get(RevenueLeakCase, case.case_id).systemic_event_id == e.systemic_event_id


def test_case_fk_rejects_unknown_event(db, make_case):
    case = make_case()
    case.systemic_event_id = uuid.uuid4()
    with pytest.raises(IntegrityError):
        db.flush()


def test_referenced_systemic_event_cannot_be_deleted(db, make_case):
    case = make_case()
    e = SystemicEvent(
        merchant_id=case.merchant_id,
        scope=SystemicScope.NETWORK_WIDE,
        failure_rate_at_detection=Decimal("8"),
        detected_at=DETECTED_AT,
    )
    db.add(e)
    db.flush()
    case.systemic_event_id = e.systemic_event_id
    db.flush()

    db.delete(e)
    with pytest.raises(IntegrityError):
        db.flush()


def test_case_systemic_event_id_still_nullable(db, make_case):
    case = make_case()
    assert case.systemic_event_id is None
    db.flush()  # a case with no systemic event is fine


# --- pure predicate: systemic_threshold_breached ------------------

_FLOORS = {"baseline_floor": 1.0, "absolute_floor": 20, "multiplier": 5}


def test_threshold_breached_all_conditions_met():
    assert systemic_threshold_breached(
        failure_rate=50, baseline_rate=5, absolute_count=30, **_FLOORS
    )


def test_threshold_exact_spike_boundary_is_a_breach():
    assert systemic_threshold_breached(
        failure_rate=25, baseline_rate=5, absolute_count=30, **_FLOORS
    )


def test_threshold_just_below_spike_is_not_a_breach():
    assert not systemic_threshold_breached(
        failure_rate=24.99, baseline_rate=5, absolute_count=30, **_FLOORS
    )


def test_threshold_baseline_below_floor_blocks_breach():
    assert not systemic_threshold_breached(
        failure_rate=100, baseline_rate=0.5, absolute_count=100, **_FLOORS
    )


def test_threshold_baseline_exactly_at_floor_ok():
    assert systemic_threshold_breached(
        failure_rate=100, baseline_rate=1.0, absolute_count=100, **_FLOORS
    )


def test_threshold_absolute_count_below_floor_blocks_breach():
    assert not systemic_threshold_breached(
        failure_rate=100, baseline_rate=5, absolute_count=19, **_FLOORS
    )


def test_threshold_absolute_count_exactly_at_floor_ok():
    assert systemic_threshold_breached(
        failure_rate=100, baseline_rate=5, absolute_count=20, **_FLOORS
    )


def test_threshold_uses_policy_config_defaults():
    p = get_policy()
    assert systemic_threshold_breached(
        failure_rate=p.systemic_spike_multiplier * p.systemic_baseline_floor_per_min,
        baseline_rate=p.systemic_baseline_floor_per_min,
        absolute_count=p.systemic_absolute_count_floor,
        baseline_floor=p.systemic_baseline_floor_per_min,
        absolute_floor=p.systemic_absolute_count_floor,
        multiplier=p.systemic_spike_multiplier,
    )


# --- pure predicate: systemic_resolved --------------------------


def test_resolved_true_at_sustain_window():
    assert systemic_resolved(minutes_below_threshold=10, sustain_window_minutes=10)


def test_resolved_false_below_sustain_window():
    assert not systemic_resolved(minutes_below_threshold=9.9, sustain_window_minutes=10)


def test_resolved_true_past_sustain_window():
    assert systemic_resolved(minutes_below_threshold=15, sustain_window_minutes=10)
