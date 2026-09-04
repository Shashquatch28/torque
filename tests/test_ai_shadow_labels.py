"""Phase 7 — `torque.ai.shadow.labels` correctness.

Cross-checks the two local mirrors this module maintains (terminal-status
population, per `torque.ai.retrieval`'s own precedent; the Module 9b
recovered-label definition) against the real functions they mirror. Test
files, unlike `src/torque/ai/*`, are free to import the forbidden modules
being mirrored — that is exactly the point of the cross-check.
"""

from __future__ import annotations

from torque.ai.shadow.labels import is_training_eligible, recovered_label
from torque.enums import CaseStatus, LegType


def test_training_eligibility_mirrors_state_machine_is_terminal_exactly():
    from torque.ai.shadow.labels import _terminal_statuses_for_leg
    from torque.state_machine import is_terminal

    for leg in LegType:
        mirrored = _terminal_statuses_for_leg(leg)
        for status in CaseStatus:
            assert (status in mirrored) == is_terminal(status, leg), (
                f"mirror diverges from state_machine.is_terminal at "
                f"status={status!r}, leg_type={leg!r}"
            )
            assert is_training_eligible(status, leg) == is_terminal(status, leg)


def test_recovered_label_mirrors_module_9b_intent_to_treat_exactly():
    from torque.ai.shadow.labels import _RECOVERED_STATUSES
    from torque.reporting.incrementality import _RECOVERED_STATUSES as real_recovered

    assert _RECOVERED_STATUSES == real_recovered
    for status in CaseStatus:
        assert recovered_label(status) == (status in real_recovered)


def test_recovered_label_is_true_only_for_recovered_and_cancelled():
    assert recovered_label(CaseStatus.RECOVERED) is True
    assert recovered_label(CaseStatus.CANCELLED) is True
    assert recovered_label(CaseStatus.EXHAUSTED) is False
    assert recovered_label(CaseStatus.WRITTEN_OFF) is False
    assert recovered_label(CaseStatus.PLAYBOOK_ACTIVE) is False


def test_partially_recovered_b2b_is_not_training_eligible_but_other_legs_terminal_is():
    assert is_training_eligible(CaseStatus.PARTIALLY_RECOVERED, LegType.B2B_RECEIVABLE) is False
    assert (
        is_training_eligible(CaseStatus.PARTIALLY_RECOVERED, LegType.PAYMENT_DEGRADATION) is True
    )


def test_open_statuses_are_never_training_eligible():
    for status in (
        CaseStatus.DETECTED,
        CaseStatus.DIAGNOSING,
        CaseStatus.SYSTEMIC_HOLD,
        CaseStatus.PLAYBOOK_ACTIVE,
        CaseStatus.ESCALATED_TO_HUMAN,
        CaseStatus.PAUSED,
    ):
        for leg in LegType:
            assert is_training_eligible(status, leg) is False
