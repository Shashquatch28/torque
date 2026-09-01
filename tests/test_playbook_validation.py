"""Blueprint Section 4.2 - `validate_playbook` + `validate_merchant_playbook_config`
(the UPI AutoPay max_attempts <= 3 defense-in-depth rule). Pure, no DB."""

from __future__ import annotations

from copy import deepcopy

import pytest

from tests.conftest import VALID_STEPS_GRAPH, VALID_STOPPING_RULES
from torque.compliance import UPI_AUTOPAY_HARD_CAP
from torque.enums import LegType, MandateType
from torque.exceptions import PlaybookValidationError
from torque.playbooks import validate_merchant_playbook_config, validate_playbook


def _rules(**over):
    return {**deepcopy(VALID_STOPPING_RULES), **over}


def test_valid_playbook_returns_normalised_dicts():
    graph, rules = validate_playbook(
        leg_type=LegType.PAYMENT_DEGRADATION,
        mandate_type=None,
        steps_graph=deepcopy(VALID_STEPS_GRAPH),
        stopping_rules=_rules(),
    )
    assert graph["entry"] == "n1"
    assert rules["max_attempts"] == 3


def test_upi_autopay_over_ceiling_rejected():
    with pytest.raises(PlaybookValidationError):
        validate_playbook(
            leg_type=LegType.SUBSCRIPTION_FAILURE,
            mandate_type=MandateType.UPI_AUTOPAY,
            steps_graph=deepcopy(VALID_STEPS_GRAPH),
            stopping_rules=_rules(max_attempts=UPI_AUTOPAY_HARD_CAP + 1),
        )


def test_upi_autopay_at_ceiling_accepted():
    validate_playbook(
        leg_type=LegType.SUBSCRIPTION_FAILURE,
        mandate_type=MandateType.UPI_AUTOPAY,
        steps_graph=deepcopy(VALID_STEPS_GRAPH),
        stopping_rules=_rules(max_attempts=UPI_AUTOPAY_HARD_CAP),
    )


@pytest.mark.parametrize("mt", [None, MandateType.CARD, MandateType.NACH])
def test_non_upi_not_subject_to_ceiling(mt):
    validate_playbook(
        leg_type=LegType.SUBSCRIPTION_FAILURE,
        mandate_type=mt,
        steps_graph=deepcopy(VALID_STEPS_GRAPH),
        stopping_rules=_rules(max_attempts=6),
    )


def test_malformed_stopping_rules_rejected():
    with pytest.raises(PlaybookValidationError):
        validate_playbook(
            leg_type=LegType.PAYMENT_DEGRADATION,
            mandate_type=None,
            steps_graph=deepcopy(VALID_STEPS_GRAPH),
            stopping_rules=_rules(max_attempts=0),
        )


def test_cyclic_graph_rejected():
    bad = deepcopy(VALID_STEPS_GRAPH)
    bad["edges"].append({"from": "n2", "condition": "on_success", "to": "n1"})
    bad["edges"].append({"from": "n2", "condition": "on_failed", "to": "n1"})
    with pytest.raises(PlaybookValidationError):
        validate_playbook(
            leg_type=LegType.PAYMENT_DEGRADATION,
            mandate_type=None,
            steps_graph=bad,
            stopping_rules=_rules(),
        )


# --- merchant override validation (against latest version) ------


def test_merchant_override_ok():
    out = validate_merchant_playbook_config(
        latest_leg_type=LegType.SUBSCRIPTION_FAILURE,
        latest_mandate_type=MandateType.CARD,
        latest_stopping_rules=_rules(),
        override={"max_attempts": 5},
    )
    assert out == {"max_attempts": 5}


def test_merchant_override_none_ok():
    assert (
        validate_merchant_playbook_config(
            latest_leg_type=LegType.PAYMENT_DEGRADATION,
            latest_mandate_type=None,
            latest_stopping_rules=_rules(),
            override=None,
        )
        is None
    )


def test_merchant_override_upi_ceiling_enforced():
    with pytest.raises(PlaybookValidationError):
        validate_merchant_playbook_config(
            latest_leg_type=LegType.SUBSCRIPTION_FAILURE,
            latest_mandate_type=MandateType.UPI_AUTOPAY,
            latest_stopping_rules=_rules(max_attempts=2),
            override={"max_attempts": 10},
        )


def test_merchant_override_malformed_partial_rejected():
    with pytest.raises(PlaybookValidationError):
        validate_merchant_playbook_config(
            latest_leg_type=LegType.PAYMENT_DEGRADATION,
            latest_mandate_type=None,
            latest_stopping_rules=_rules(),
            override={"max_attempts": 5, "unknown_key": 1},
        )
