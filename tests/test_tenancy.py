"""Blueprint Section 2.1 — application-layer multi-tenancy.

Every tenant-scoped read is filtered by merchant_id; writes are stamped;
cross-tenant writes are rejected; globally-scoped models (Counterparty) are
reachable only through the explicit `unscoped()` escape hatch.
"""

from __future__ import annotations

import pytest

from torque.db.scoped import TenantScope
from torque.enums import LegType
from torque.exceptions import CrossTenantWriteError, NonTenantModelError
from torque.models import Counterparty, RevenueLeakCase


def _case(merchant, cp, event, **kw):
    return RevenueLeakCase(
        merchant_id=merchant.merchant_id,
        leg_type=LegType.PAYMENT_DEGRADATION,
        source_event_id=event.event_id,
        counterparty_id=cp.counterparty_id,
        amount_at_risk=kw.pop("amount_at_risk", 500),
        context={"gateway": "razorpay"},
        **kw,
    )


def test_select_only_returns_own_merchant_rows(db, make_merchant, make_counterparty, make_event):
    m1, m2 = make_merchant(), make_merchant()
    cp = make_counterparty()
    e1, e2 = make_event(m1), make_event(m2)
    db.add(_case(m1, cp, e1))
    db.add(_case(m2, cp, e2))
    db.flush()

    scope1 = TenantScope(db, m1.merchant_id)
    rows = scope1.all(RevenueLeakCase)
    assert len(rows) == 1
    assert rows[0].merchant_id == m1.merchant_id


def test_get_hides_other_tenants_row_even_by_pk(db, make_merchant, make_counterparty, make_event):
    m1, m2 = make_merchant(), make_merchant()
    cp = make_counterparty()
    e2 = make_event(m2)
    other = _case(m2, cp, e2)
    db.add(other)
    db.flush()

    scope1 = TenantScope(db, m1.merchant_id)
    assert scope1.get(RevenueLeakCase, other.case_id) is None


def test_add_stamps_merchant_id(db, make_merchant, make_counterparty, make_event):
    m = make_merchant()
    cp = make_counterparty()
    ev = make_event(m)
    scope = TenantScope(db, m.merchant_id)

    case = RevenueLeakCase(
        leg_type=LegType.PAYMENT_DEGRADATION,
        source_event_id=ev.event_id,
        counterparty_id=cp.counterparty_id,
        amount_at_risk=500,
        context={"gateway": "razorpay"},
    )
    scope.add(case)
    db.flush()
    assert case.merchant_id == m.merchant_id


def test_add_rejects_cross_tenant_object(db, make_merchant, make_counterparty, make_event):
    m1, m2 = make_merchant(), make_merchant()
    cp = make_counterparty()
    e1 = make_event(m1)
    scope2 = TenantScope(db, m2.merchant_id)
    with pytest.raises(CrossTenantWriteError):
        scope2.add(_case(m1, cp, e1))


def test_select_rejects_globally_scoped_model(db, make_merchant):
    scope = TenantScope(db, make_merchant().merchant_id)
    with pytest.raises(NonTenantModelError):
        scope.select(Counterparty)


def test_unscoped_reaches_counterparty(db, make_merchant, make_counterparty):
    make_counterparty(name="Global Identity")
    scope = TenantScope(db, make_merchant().merchant_id)
    found = scope.unscoped().query(Counterparty).filter_by(name="Global Identity").one()
    assert found.name == "Global Identity"
