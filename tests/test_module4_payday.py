"""Module 4 — payday-cycle override policy (Blueprint §4.3). The policy gate only;
the timing computation is Module 5 (D-025)."""

from __future__ import annotations

from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import CaseStatus, LegType
from torque.policy.payday import effective_timing_adjustment, payday_override_enabled


def _nsf_case(make_case, merchant):
    return make_case(
        merchant=merchant, leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value, diagnosis_confidence=0.9,
        context={"gateway": "razorpay"}, suggested_timing_adjustment="next_month_end_working_day",
    )


def test_default_is_enabled(make_merchant):
    m = make_merchant()  # risk_appetite_config = {}
    assert payday_override_enabled(m) is True


def test_explicit_disable(make_merchant):
    m = make_merchant(risk_appetite_config={"payday_cycle_override_enabled": False})
    assert payday_override_enabled(m) is False


def test_effective_adjustment_applied_when_enabled(db, make_case, make_merchant):
    m = make_merchant()
    case = _nsf_case(make_case, m)
    assert effective_timing_adjustment(case, m) == "next_month_end_working_day"


def test_effective_adjustment_suppressed_when_disabled(db, make_case, make_merchant):
    m = make_merchant(risk_appetite_config={"payday_cycle_override_enabled": False})
    case = _nsf_case(make_case, m)
    # The signal is present on the case, but policy says do not apply it.
    assert case.suggested_timing_adjustment == "next_month_end_working_day"
    assert effective_timing_adjustment(case, m) is None


def test_no_adjustment_when_case_has_none(db, make_case, make_merchant):
    m = make_merchant()
    case = make_case(
        merchant=m, leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_OTHER.value, diagnosis_confidence=0.9,
        context={"gateway": "razorpay"},
    )
    assert effective_timing_adjustment(case, m) is None
