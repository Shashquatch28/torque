"""Blueprint Section 2.2 — Counterparty is the single PII source; erasure nulls
those fields and leaves all downstream history structurally intact."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from torque.enums import Actor, CaseEventType, LegType
from torque.events import append_case_event
from torque.exceptions import CohortAlreadyAssignedError
from torque.models import Counterparty, MerchantCounterparty, RevenueLeakCase


def test_merchant_counterparty_unique_together(db, make_merchant, make_counterparty):
    m = make_merchant()
    cp = make_counterparty()
    db.add(MerchantCounterparty(merchant_id=m.merchant_id, counterparty_id=cp.counterparty_id))
    db.flush()
    db.add(MerchantCounterparty(merchant_id=m.merchant_id, counterparty_id=cp.counterparty_id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_cohort_assigned_once_then_immutable(db, make_merchant, make_counterparty):
    m = make_merchant()
    cp = make_counterparty()
    mc = MerchantCounterparty(merchant_id=m.merchant_id, counterparty_id=cp.counterparty_id)
    db.add(mc)
    db.flush()

    mc.assign_cohort(True)
    assert mc.in_control_cohort is True
    assert mc.cohort_assigned_at is not None
    with pytest.raises(CohortAlreadyAssignedError):
        mc.assign_cohort(False)


def test_erasure_nulls_pii_but_keeps_history(
    db, make_merchant, make_counterparty, make_event
):
    m = make_merchant()
    cp = make_counterparty(name="Asha Rao", phone="+919812345678", email="asha@example.com")
    ev = make_event(m)
    case = RevenueLeakCase(
        merchant_id=m.merchant_id,
        leg_type=LegType.PAYMENT_DEGRADATION,
        source_event_id=ev.event_id,
        counterparty_id=cp.counterparty_id,
        amount_at_risk=2500,
        context={"gateway": "razorpay"},
    )
    db.add(case)
    db.flush()
    append_case_event(
        db,
        case_id=case.case_id,
        event_type=CaseEventType.STATUS_CHANGED,
        payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "test"},
        actor=Actor.SYSTEM,
        counterparty_id=cp.counterparty_id,
    )
    db.flush()

    cp.redact_pii(source="unit-test")
    db.flush()

    refreshed = db.get(Counterparty, cp.counterparty_id)
    assert refreshed.name is None and refreshed.phone is None and refreshed.email is None
    assert refreshed.consent_log[-1]["action"] == "erased"

    # Case + event rows still resolve via counterparty_id.
    assert db.get(RevenueLeakCase, case.case_id).counterparty_id == cp.counterparty_id
    n_events = db.execute(
        text("SELECT count(*) FROM case_event WHERE counterparty_id = :c"),
        {"c": cp.counterparty_id},
    ).scalar()
    assert n_events == 1


def test_language_pref_enum_enforced(db, make_counterparty):
    cp = make_counterparty()
    db.flush()
    with pytest.raises(DBAPIError):
        db.execute(
            text("UPDATE counterparty SET language_pref = 'FRENCH' WHERE counterparty_id = :c"),
            {"c": cp.counterparty_id},
        )
