"""Blueprint Section 4 + Part C item 1 + confirmed R4 — the RevenueLeakCase
status state machine."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from torque.enums import CaseStatus, LegType
from torque.exceptions import IllegalTransitionError
from torque.models import RevenueLeakCase
from torque.state_machine import (
    allowed_targets,
    assert_transition,
    is_terminal,
    transition_case,
)


def _case(db, m, cp, ev, *, leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.DETECTED):
    ctx = {} if leg is LegType.B2B_RECEIVABLE else {"gateway": "razorpay"}
    case = RevenueLeakCase(
        merchant_id=m.merchant_id,
        leg_type=leg,
        source_event_id=ev.event_id,
        counterparty_id=cp.counterparty_id,
        amount_at_risk=1000,
        status=status,
        context=ctx,
    )
    db.add(case)
    db.flush()
    return case


def test_detected_to_diagnosing_is_legal():
    assert_transition(CaseStatus.DETECTED, CaseStatus.DIAGNOSING, LegType.PAYMENT_DEGRADATION)


def test_detected_to_playbook_active_is_illegal():
    with pytest.raises(IllegalTransitionError):
        assert_transition(
            CaseStatus.DETECTED, CaseStatus.PLAYBOOK_ACTIVE, LegType.PAYMENT_DEGRADATION
        )


def test_diagnosing_to_escalated_direct_edge_part_c():
    assert CaseStatus.ESCALATED_TO_HUMAN in allowed_targets(
        CaseStatus.DIAGNOSING, LegType.SUBSCRIPTION_FAILURE
    )


def test_partially_recovered_terminal_for_non_b2b():
    assert is_terminal(CaseStatus.PARTIALLY_RECOVERED, LegType.PAYMENT_DEGRADATION)
    with pytest.raises(IllegalTransitionError):
        assert_transition(
            CaseStatus.PARTIALLY_RECOVERED,
            CaseStatus.PLAYBOOK_ACTIVE,
            LegType.SUBSCRIPTION_FAILURE,
        )


def test_partially_recovered_loops_for_b2b():
    assert not is_terminal(CaseStatus.PARTIALLY_RECOVERED, LegType.B2B_RECEIVABLE)
    assert_transition(
        CaseStatus.PARTIALLY_RECOVERED,
        CaseStatus.PLAYBOOK_ACTIVE,
        LegType.B2B_RECEIVABLE,
    )


def test_transition_case_writes_status_changed_event(
    db, make_merchant, make_counterparty, make_event
):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    case = _case(db, m, cp, ev)
    transition_case(db, case, CaseStatus.DIAGNOSING, trigger="ingestion_complete")
    db.flush()

    assert case.status is CaseStatus.DIAGNOSING
    row = db.execute(
        text(
            "SELECT event_type, payload FROM case_event WHERE case_id = :c "
            "ORDER BY event_seq_id DESC LIMIT 1"
        ),
        {"c": case.case_id},
    ).one()
    assert row.event_type == "STATUS_CHANGED"
    assert row.payload == {
        "from_status": "DETECTED",
        "to_status": "DIAGNOSING",
        "trigger": "ingestion_complete",
    }


def test_transition_case_rejects_illegal(db, make_merchant, make_counterparty, make_event):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    case = _case(db, m, cp, ev)
    with pytest.raises(IllegalTransitionError):
        transition_case(db, case, CaseStatus.RECOVERED, trigger="nope")


# --- Milestone 7c — U-01 #3: PLAYBOOK_ACTIVE -> SYSTEMIC_HOLD (approved) ---


def test_playbook_active_to_systemic_hold_is_legal():
    assert_transition(
        CaseStatus.PLAYBOOK_ACTIVE, CaseStatus.SYSTEMIC_HOLD, LegType.PAYMENT_DEGRADATION
    )


def test_playbook_active_targets_are_exactly_expected():
    assert allowed_targets(CaseStatus.PLAYBOOK_ACTIVE, LegType.PAYMENT_DEGRADATION) == {
        CaseStatus.RECOVERED,
        CaseStatus.PARTIALLY_RECOVERED,
        CaseStatus.EXHAUSTED,
        CaseStatus.ESCALATED_TO_HUMAN,
        CaseStatus.PAUSED,
        CaseStatus.CANCELLED,
        CaseStatus.SYSTEMIC_HOLD,
    }


def test_systemic_hold_targets_unchanged():
    # resume is only ever -> DIAGNOSING; no SYSTEMIC_HOLD -> PLAYBOOK_ACTIVE edge
    assert allowed_targets(CaseStatus.SYSTEMIC_HOLD, LegType.PAYMENT_DEGRADATION) == {
        CaseStatus.DIAGNOSING
    }


def test_diagnosing_to_systemic_hold_still_illegal():
    with pytest.raises(IllegalTransitionError):
        assert_transition(
            CaseStatus.DIAGNOSING, CaseStatus.SYSTEMIC_HOLD, LegType.PAYMENT_DEGRADATION
        )


def test_detected_to_cancelled_still_illegal():
    with pytest.raises(IllegalTransitionError):
        assert_transition(
            CaseStatus.DETECTED, CaseStatus.CANCELLED, LegType.PAYMENT_DEGRADATION
        )


def test_diagnosing_to_cancelled_still_illegal():
    with pytest.raises(IllegalTransitionError):
        assert_transition(
            CaseStatus.DIAGNOSING, CaseStatus.CANCELLED, LegType.PAYMENT_DEGRADATION
        )


def test_transition_case_executes_playbook_active_to_systemic_hold(
    db, make_merchant, make_counterparty, make_event
):
    m, cp = make_merchant(), make_counterparty()
    ev = make_event(m)
    case = _case(db, m, cp, ev, status=CaseStatus.PLAYBOOK_ACTIVE)
    transition_case(db, case, CaseStatus.SYSTEMIC_HOLD, trigger="systemic_network_wide")
    db.flush()

    assert case.status is CaseStatus.SYSTEMIC_HOLD
    row = db.execute(
        text(
            "SELECT event_type, payload FROM case_event WHERE case_id = :c "
            "ORDER BY event_seq_id DESC LIMIT 1"
        ),
        {"c": case.case_id},
    ).one()
    assert row.event_type == "STATUS_CHANGED"
    assert row.payload == {
        "from_status": "PLAYBOOK_ACTIVE",
        "to_status": "SYSTEMIC_HOLD",
        "trigger": "systemic_network_wide",
    }
