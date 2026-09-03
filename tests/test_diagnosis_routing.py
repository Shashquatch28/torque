"""Module 3 — confidence-threshold routing (Blueprint §3.3 / Decision E).

`T` is a policy value, not a literal: routing follows
`PolicyConfig.diagnosis_confidence_threshold`, and the boundary is `>= T` →
playbook, `< T` → escalate.
"""

from __future__ import annotations

import pytest

from torque.config import PolicyConfig
from torque.diagnosis import diagnose_case
from torque.diagnosis.engine import DiagnosisOutcome
from torque.enums import CaseStatus, LegType


@pytest.fixture()
def set_threshold(monkeypatch):
    def _set(value: float):
        policy = PolicyConfig(diagnosis_confidence_threshold=value)
        monkeypatch.setattr("torque.diagnosis.engine.get_policy", lambda: policy)
        return policy

    return _set


def _payment_case(make_case, decline_code):
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay", "decline_code": decline_code},
    )


def test_default_threshold_is_065():
    assert PolicyConfig().diagnosis_confidence_threshold == 0.65


def test_high_threshold_escalates_a_normally_confident_case(db, make_case, set_threshold):
    set_threshold(0.9)  # 0.75 NSF now below T
    case = _payment_case(make_case, "insufficient_funds")
    assert diagnose_case(db, case_id=case.case_id) is DiagnosisOutcome.ESCALATED
    db.refresh(case)
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN


def test_low_threshold_routes_a_normally_escalated_case(db, make_case, set_threshold):
    set_threshold(0.5)  # a checkout UPI_COLLECT (0.6) now clears T
    case = make_case(
        leg=LegType.CHECKOUT_ABANDONMENT,
        context={
            "cart_id": "c1",
            "cart_value": "10.00",
            "drop_stage": "vpa_entry",
            "payment_method_attempted": "UPI_COLLECT",
        },
    )
    assert diagnose_case(db, case_id=case.case_id) is DiagnosisOutcome.ROUTED_TO_PLAYBOOK
    db.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE


def test_confidence_exactly_at_threshold_routes_to_playbook(db, make_case, set_threshold):
    """`diagnosis_confidence == T` is NOT below T → playbook (§3.3 uses `< T`)."""
    set_threshold(0.75)  # exactly the NSF known-code confidence
    case = _payment_case(make_case, "insufficient_funds")
    assert diagnose_case(db, case_id=case.case_id) is DiagnosisOutcome.ROUTED_TO_PLAYBOOK
