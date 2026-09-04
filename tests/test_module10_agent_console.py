"""Module 10 §10.8 — Agent Console human overrides: resolve / pause / unpause.

Uses the existing legal `ESCALATED_TO_HUMAN → {RECOVERED, PARTIALLY_RECOVERED,
WRITTEN_OFF}` and `PLAYBOOK_ACTIVE ↔ PAUSED` edges. Writes `escalation_resolution`
+ a `HUMAN_RESOLVED` event; a recovering resolution records
`recovery_type` / `recovered_amount` through `guards.human_resolution_writer`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from torque.agent_console import EscalationResolution, resolve_escalation
from torque.agent_console.resolve import pause_case, unpause_case
from torque.coordination import human_queue as HQ
from torque.enums import Actor, CaseEventType, CaseStatus, LegType, RecoveryType
from torque.exceptions import CaseNotFoundError, HumanResolutionError, OwnershipViolation
from torque.models import CaseEvent, HumanQueueEntry


def _escalated(make_case, m=None, cp=None, amount="12000.00", **kw):
    return make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay"}, amount_at_risk=Decimal(amount),
        status=CaseStatus.ESCALATED_TO_HUMAN, **kw,
    )


def _events(db, case_id):
    return db.scalars(
        select(CaseEvent).where(CaseEvent.case_id == case_id)
        .order_by(CaseEvent.event_seq_id)
    ).all()


def test_resolve_recovered_by_human(db, make_case):
    case = _escalated(make_case, amount="12400.00")
    HQ.enqueue(db, case=case, reason=HQ.HumanQueueReason.LOW_CONFIDENCE_DIAGNOSIS)

    out = resolve_escalation(
        db, merchant_id=case.merchant_id, case_id=case.case_id,
        resolution=EscalationResolution.RECOVERED_BY_HUMAN, agent_id="agent-7",
    )
    assert out.to_status == "RECOVERED"
    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED
    assert case.recovered_amount == Decimal("12400.00")  # defaulted to amount_at_risk
    assert case.escalation_resolution == "RECOVERED_BY_HUMAN"
    assert case.escalation_resolved_by == "agent-7"
    assert case.escalation_resolved_at is not None
    assert case.closed_at is not None
    # HUMAN_RESOLVED event written by the human actor, correct payload
    hr = [e for e in _events(db, case.case_id) if e.event_type == CaseEventType.HUMAN_RESOLVED]
    assert len(hr) == 1
    assert hr[0].actor is Actor.HUMAN
    assert hr[0].payload == {"resolution": "RECOVERED_BY_HUMAN", "agent_id": "agent-7"}
    # removed from the human queue
    assert db.scalars(
        select(HumanQueueEntry).where(HumanQueueEntry.case_id == case.case_id)
    ).first() is None


def test_resolve_partial_with_explicit_amount(db, make_case):
    case = _escalated(make_case, amount="20000.00")
    out = resolve_escalation(
        db, merchant_id=case.merchant_id, case_id=case.case_id,
        resolution=EscalationResolution.PARTIALLY_RECOVERED_BY_HUMAN,
        agent_id="a", recovered_amount=Decimal("8000.00"),
    )
    assert out.to_status == "PARTIALLY_RECOVERED"
    db.refresh(case)
    assert case.recovered_amount == Decimal("8000.00")
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED
    assert case.status is CaseStatus.PARTIALLY_RECOVERED
    # non-B2B PARTIALLY_RECOVERED is terminal → closed
    assert case.closed_at is not None


def test_resolve_written_off_records_no_recovery(db, make_case):
    case = _escalated(make_case, amount="5000.00")
    resolve_escalation(
        db, merchant_id=case.merchant_id, case_id=case.case_id,
        resolution=EscalationResolution.WRITTEN_OFF, agent_id="a",
    )
    db.refresh(case)
    assert case.status is CaseStatus.WRITTEN_OFF
    assert case.recovery_type is None
    assert case.recovered_amount is None
    assert case.escalation_resolution == "WRITTEN_OFF"


def test_resolve_b2b_partial_stays_open(db, make_case):
    from tests.module9_helpers import add_invoice

    case = make_case(leg=LegType.B2B_RECEIVABLE, context={},
                     amount_at_risk=Decimal("10000.00"),
                     status=CaseStatus.ESCALATED_TO_HUMAN)
    add_invoice(db, case, original="10000.00", outstanding="10000.00")
    resolve_escalation(
        db, merchant_id=case.merchant_id, case_id=case.case_id,
        resolution=EscalationResolution.PARTIALLY_RECOVERED_BY_HUMAN,
        agent_id="a", recovered_amount=Decimal("4000.00"),
    )
    db.refresh(case)
    assert case.status is CaseStatus.PARTIALLY_RECOVERED
    assert case.closed_at is None  # B2B keeps dunning


def test_resolve_rejects_non_escalated_case(db, make_case):
    case = _escalated(make_case)
    case.status = CaseStatus.PLAYBOOK_ACTIVE
    db.flush()
    with pytest.raises(HumanResolutionError, match="ESCALATED_TO_HUMAN"):
        resolve_escalation(
            db, merchant_id=case.merchant_id, case_id=case.case_id,
            resolution=EscalationResolution.WRITTEN_OFF, agent_id="a",
        )


def test_resolve_rejects_missing_agent_and_bad_amount(db, make_case):
    case = _escalated(make_case)
    with pytest.raises(HumanResolutionError):
        resolve_escalation(db, merchant_id=case.merchant_id, case_id=case.case_id,
                           resolution=EscalationResolution.WRITTEN_OFF, agent_id="")
    case2 = _escalated(make_case)
    with pytest.raises(HumanResolutionError, match="positive"):
        resolve_escalation(db, merchant_id=case2.merchant_id, case_id=case2.case_id,
                           resolution=EscalationResolution.RECOVERED_BY_HUMAN,
                           agent_id="a", recovered_amount=Decimal("0"))


def test_resolve_cross_tenant_is_case_not_found(db, make_case, make_merchant):
    other = make_merchant()
    case = _escalated(make_case)
    with pytest.raises(CaseNotFoundError):
        resolve_escalation(db, merchant_id=other.merchant_id, case_id=case.case_id,
                           resolution=EscalationResolution.WRITTEN_OFF, agent_id="a")


def test_pause_and_unpause(db, make_case):
    case = make_case(leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
                     amount_at_risk=Decimal("3000.00"), status=CaseStatus.PLAYBOOK_ACTIVE)
    HQ.enqueue(db, case=case, reason=HQ.HumanQueueReason.PROMISE_BROKEN)
    out = pause_case(db, merchant_id=case.merchant_id, case_id=case.case_id, agent_id="a")
    assert out.to_status == "PAUSED"
    db.refresh(case)
    assert case.status is CaseStatus.PAUSED
    # still queued — pause is not resolution
    assert db.scalars(
        select(HumanQueueEntry).where(HumanQueueEntry.case_id == case.case_id)
    ).first() is not None

    out2 = unpause_case(db, merchant_id=case.merchant_id, case_id=case.case_id, agent_id="a")
    assert out2.to_status == "PLAYBOOK_ACTIVE"
    db.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE


def test_pause_rejects_non_playbook_active(db, make_case):
    case = _escalated(make_case)
    with pytest.raises(HumanResolutionError):
        pause_case(db, merchant_id=case.merchant_id, case_id=case.case_id, agent_id="a")


def test_recovery_fields_are_still_guarded_outside_the_writer(db, make_case):
    """The `human_resolution_writer` gate is real — a bare write still raises."""
    case = _escalated(make_case)
    case.recovery_type = RecoveryType.AGENT_ASSISTED
    with pytest.raises(OwnershipViolation):
        db.flush()
    db.rollback()
