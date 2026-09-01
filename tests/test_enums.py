"""Enum vocabulary matches the blueprint and round-trips through Postgres."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, DBAPIError

from torque.enums import (
    ALL_ENUMS,
    Actor,
    CaseEventType,
    CaseStatus,
    LegType,
    MacTier,
    PaymentLinkStatus,
)


def test_leg_type_values():
    assert {e.value for e in LegType} == {
        "PAYMENT_DEGRADATION",
        "CHECKOUT_ABANDONMENT",
        "SUBSCRIPTION_FAILURE",
        "B2B_RECEIVABLE",
    }


def test_case_status_has_exactly_the_confirmed_eleven_values():
    assert {e.value for e in CaseStatus} == {
        "DETECTED",
        "SYSTEMIC_HOLD",
        "DIAGNOSING",
        "PLAYBOOK_ACTIVE",
        "RECOVERED",
        "PARTIALLY_RECOVERED",
        "EXHAUSTED",
        "ESCALATED_TO_HUMAN",
        "PAUSED",
        "CANCELLED",
        "WRITTEN_OFF",
    }


def test_case_event_type_count_matches_section_4():
    assert len(list(CaseEventType)) == 10


def test_payment_link_status_is_lowercase():
    assert [e.value for e in PaymentLinkStatus] == [
        "issued",
        "partially_paid",
        "paid",
        "expired",
        "cancelled",
    ]


def test_mac_tier_values():
    assert {e.value for e in MacTier} == {
        "TIER_1_HARD_STOP",
        "TIER_2_CAPPED_RETRY",
        "TIER_3_INSTRUMENT_DEAD",
        "TIMED_RETRY",
    }


def test_every_enum_type_exists_in_postgres(engine):
    with engine.connect() as conn:
        pg_enums = set(
            conn.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
            .scalars()
            .all()
        )
    # 0001 creates one type per enum in ALL_ENUMS.
    assert len(pg_enums) >= len(ALL_ENUMS)
    for name in ("leg_type", "case_status", "mac_tier", "case_event_type", "actor"):
        assert name in pg_enums


def test_case_status_column_rejects_unknown_value(db, make_merchant, make_counterparty, make_event):
    m = make_merchant()
    cp = make_counterparty()
    ev = make_event(m)
    # The bad enum literal is rejected by Postgres at statement execution.
    with pytest.raises((DataError, DBAPIError)):
        db.execute(
            text(
                "INSERT INTO revenue_leak_case "
                "(merchant_id, leg_type, source_event_id, counterparty_id, "
                " amount_at_risk, status, context) "
                "VALUES (:m, 'PAYMENT_DEGRADATION', :e, :c, 100, :bad, '{}'::jsonb)"
            ),
            {
                "m": m.merchant_id,
                "e": ev.event_id,
                "c": cp.counterparty_id,
                "bad": "NOT_A_STATUS",
            },
        )


def test_actor_enum_round_trips(db, make_merchant, make_counterparty, make_event):
    from torque.enums import CaseEventType as CET
    from torque.events import append_case_event
    from torque.models import RevenueLeakCase

    m = make_merchant()
    cp = make_counterparty()
    ev = make_event(m)
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
    append_case_event(
        db,
        case_id=case.case_id,
        event_type=CET.HUMAN_RESOLVED,
        payload={"resolution": "manual", "agent_id": "agent_1"},
        actor=Actor.HUMAN,
    )
    db.flush()
    row = db.execute(text("SELECT actor FROM case_event LIMIT 1")).scalar()
    assert row == "HUMAN"
