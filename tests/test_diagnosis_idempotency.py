"""Module 3 — eligibility & idempotency (Blueprint §3.3, and the §2.5 handoff).

Diagnosis must be safe under repeated execution and must refuse ineligible cases:
already-diagnosed, terminal, superseded (§2.4), and actively-held (SYSTEMIC_HOLD)
cases are all no-ops. A systemic-RESUMED case (Module 2 §2.5 moves it straight to
DIAGNOSING) is diagnosable and skips the DETECTED→DIAGNOSING hop.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from torque.diagnosis import diagnose_case
from torque.diagnosis.engine import DiagnosisOutcome
from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import CaseEventType, CaseStatus, LegType
from torque.models import CaseEvent


def _payment_case(make_case, **kw):
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "insufficient_funds"},
        **kw,
    )


def _event_count(db, case):
    return int(
        db.scalar(
            select(func.count()).select_from(CaseEvent).where(CaseEvent.case_id == case.case_id)
        )
    )


def test_missing_case_is_noop(db):
    assert diagnose_case(db, case_id=uuid.uuid4()) is DiagnosisOutcome.NOOP


def test_repeated_diagnosis_is_noop(db, make_case):
    case = _payment_case(make_case)
    first = diagnose_case(db, case_id=case.case_id)
    assert first is DiagnosisOutcome.ROUTED_TO_PLAYBOOK
    events_after_first = _event_count(db, case)

    second = diagnose_case(db, case_id=case.case_id)
    assert second is DiagnosisOutcome.NOOP
    assert _event_count(db, case) == events_after_first  # no new writes


def test_escalated_case_not_rediagnosed(db, make_case):
    case = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": "BAD_REQUEST_ERROR"},
    )
    assert diagnose_case(db, case_id=case.case_id) is DiagnosisOutcome.ESCALATED
    assert diagnose_case(db, case_id=case.case_id) is DiagnosisOutcome.NOOP


def test_terminal_case_is_noop(db, make_case):
    case = _payment_case(make_case, status=CaseStatus.RECOVERED)
    assert diagnose_case(db, case_id=case.case_id) is DiagnosisOutcome.NOOP
    assert _event_count(db, case) == 0


def test_systemic_hold_case_is_noop(db, make_case, make_merchant):
    """A case actively held at SYSTEMIC_HOLD is not diagnosed — outreach and
    diagnosis are both suppressed until Module 2 §2.5 resolves the outage."""
    case = _payment_case(make_case, status=CaseStatus.SYSTEMIC_HOLD)
    assert diagnose_case(db, case_id=case.case_id) is DiagnosisOutcome.NOOP


def test_superseded_case_is_noop(db, make_case, make_merchant, make_counterparty):
    """A §2.4-merged narrower case (superseded_by_case_id set) is skipped — the
    surviving canonical case is the one that gets diagnosed."""
    m, cp = make_merchant(), make_counterparty()
    survivor = _payment_case(make_case, merchant=m, counterparty=cp)
    narrower = make_case(
        merchant=m,
        counterparty=cp,
        leg=LegType.CHECKOUT_ABANDONMENT,
        context={
            "cart_id": "c1",
            "cart_value": "10.00",
            "drop_stage": "vpa_entry",
            "payment_method_attempted": "UPI_COLLECT",
        },
    )
    narrower.superseded_by_case_id = survivor.case_id
    db.flush()

    assert diagnose_case(db, case_id=narrower.case_id) is DiagnosisOutcome.NOOP
    assert _event_count(db, narrower) == 0


def test_systemic_resumed_diagnosing_case_skips_the_detected_hop(db, make_case):
    """A case Module 2 §2.5 re-queued to DIAGNOSING (root_cause still unset) is
    diagnosed without a DETECTED→DIAGNOSING transition."""
    case = _payment_case(make_case, status=CaseStatus.DIAGNOSING)
    out = diagnose_case(db, case_id=case.case_id)

    assert out is DiagnosisOutcome.ROUTED_TO_PLAYBOOK
    db.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE
    status_events = db.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .where(CaseEvent.event_type == CaseEventType.STATUS_CHANGED)
    ).all()
    froms = {e.payload["from_status"] for e in status_events}
    assert "DETECTED" not in froms  # never re-entered DIAGNOSING from DETECTED
    assert froms == {"DIAGNOSING"}


def test_diagnosing_case_already_classified_is_noop(db, make_case):
    """A DIAGNOSING case that already carries a root_cause_code (a crash-recovery
    edge) is not re-diagnosed."""
    case = _payment_case(
        make_case,
        status=CaseStatus.DIAGNOSING,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value,
    )
    assert diagnose_case(db, case_id=case.case_id) is DiagnosisOutcome.NOOP
