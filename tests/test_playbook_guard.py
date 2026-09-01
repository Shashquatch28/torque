"""The `before_flush` guard enforces playbook validation with no bypass through
a plain `session.add()`, and rolls back the whole transaction on failure."""

from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import func, select

from tests.conftest import VALID_STEPS_GRAPH, VALID_STOPPING_RULES
from torque.enums import LegType, MandateType
from torque.events import atomic
from torque.exceptions import PlaybookValidationError
from torque.models import Merchant, MerchantPlaybookConfig, Playbook, PlaybookIdentity


def test_bad_playbook_blocked_on_plain_add_and_rolls_back(db):
    db.add(PlaybookIdentity(playbook_id="pb_guard"))
    db.flush()

    n_before = db.scalar(select(func.count()).select_from(Merchant))
    cyclic = deepcopy(VALID_STEPS_GRAPH)
    cyclic["edges"].append({"from": "n2", "condition": "on_success", "to": "n1"})
    cyclic["edges"].append({"from": "n2", "condition": "on_failed", "to": "n1"})

    with pytest.raises(PlaybookValidationError):
        with atomic(db):
            db.add(Merchant(merchant_id="acc_guard_sibling", channels_enabled=[]))
            db.flush()
            db.add(
                Playbook(
                    playbook_id="pb_guard",
                    version=1,
                    leg_type=LegType.PAYMENT_DEGRADATION,
                    steps_graph=cyclic,
                    stopping_rules=deepcopy(VALID_STOPPING_RULES),
                )
            )
            db.flush()

    # the sibling Merchant insert was rolled back with the bad Playbook
    assert db.scalar(select(func.count()).select_from(Merchant)) == n_before


def test_playbook_steps_graph_normalised_on_insert(db, make_playbook):
    # the fixture graph uses the "from" alias; after the guard it round-trips
    pb = make_playbook()
    db.refresh(pb)
    assert pb.steps_graph["edges"][0]["from"] == "n1"
    assert pb.stopping_rules["max_attempts"] == 3


def test_bad_merchant_config_override_blocked_on_plain_add(db, make_merchant, make_playbook):
    m = make_merchant()
    upi_pb = make_playbook(
        playbook_id="pb_guard_upi",
        leg_type=LegType.SUBSCRIPTION_FAILURE,
        mandate_type=MandateType.UPI_AUTOPAY,
        stopping_rules={**deepcopy(VALID_STOPPING_RULES), "max_attempts": 3},
    )
    db.add(
        MerchantPlaybookConfig(
            merchant_id=m.merchant_id,
            playbook_id=upi_pb.playbook_id,
            stopping_rules_override={"max_attempts": 12},
        )
    )
    with pytest.raises(PlaybookValidationError):
        db.flush()
