"""Module 6 §6.3 (Q-D) — `escalation_ceiling <= max_attempts` at playbook-save time.

Enforced through the existing `torque.playbooks` validation mechanism (the same
path as the UPI AutoPay ceiling), on the base rules and on any merchant override
merged onto them.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from tests.conftest import VALID_STEPS_GRAPH, VALID_STOPPING_RULES
from torque.enums import LegType
from torque.exceptions import PlaybookValidationError
from torque.playbooks import validate_merchant_playbook_config, validate_playbook
from torque.policy import catalog as C


def _rules(**over):
    return {**deepcopy(VALID_STOPPING_RULES), **over}


def test_ceiling_above_max_attempts_rejected():
    with pytest.raises(PlaybookValidationError, match="escalation_ceiling"):
        validate_playbook(
            leg_type=LegType.PAYMENT_DEGRADATION,
            mandate_type=None,
            steps_graph=deepcopy(VALID_STEPS_GRAPH),
            stopping_rules=_rules(max_attempts=2, escalation_ceiling=3),
        )


def test_ceiling_equal_to_max_attempts_accepted():
    _, rules = validate_playbook(
        leg_type=LegType.PAYMENT_DEGRADATION,
        mandate_type=None,
        steps_graph=deepcopy(VALID_STEPS_GRAPH),
        stopping_rules=_rules(max_attempts=3, escalation_ceiling=3),
    )
    assert rules["escalation_ceiling"] == 3


def test_merchant_override_lowering_max_attempts_below_ceiling_rejected():
    with pytest.raises(PlaybookValidationError, match="escalation_ceiling"):
        validate_merchant_playbook_config(
            latest_leg_type=LegType.PAYMENT_DEGRADATION,
            latest_mandate_type=None,
            latest_stopping_rules=_rules(max_attempts=4, escalation_ceiling=3),
            override={"max_attempts": 2},
        )


def test_merchant_override_lowering_both_accepted():
    out = validate_merchant_playbook_config(
        latest_leg_type=LegType.PAYMENT_DEGRADATION,
        latest_mandate_type=None,
        latest_stopping_rules=_rules(max_attempts=4, escalation_ceiling=3),
        override={"max_attempts": 2, "escalation_ceiling": 2},
    )
    assert out == {"max_attempts": 2, "escalation_ceiling": 2}


def test_every_catalog_playbook_satisfies_the_bound(db):
    """The seeded catalog must already be coherent (a re-seed would flush each
    graph through the guard)."""
    for entry in C.CATALOG:
        rules = entry.stopping_rules
        assert rules["escalation_ceiling"] <= rules["max_attempts"], entry.playbook_id
    # and seeding actually succeeds through the ORM guard
    from torque.policy import seed_catalog

    seed_catalog(db)
