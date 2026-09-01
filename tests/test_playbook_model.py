"""Blueprint Section 2.4 / Section 3 - `playbook_identity` + append-only
`playbook` versions."""

from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.conftest import VALID_STEPS_GRAPH, VALID_STOPPING_RULES
from torque.db.scoped import TenantScope
from torque.enums import LegType
from torque.exceptions import AppendOnlyViolation, NonTenantModelError
from torque.models import Playbook, PlaybookIdentity


def test_new_version_row_coexists_and_old_is_intact(db, make_playbook):
    v1 = make_playbook(playbook_id="pb_versioned", version=1)
    original_graph = deepcopy(v1.steps_graph)

    v2 = Playbook(
        playbook_id="pb_versioned",
        version=2,
        leg_type=LegType.PAYMENT_DEGRADATION,
        steps_graph=deepcopy(VALID_STEPS_GRAPH),
        stopping_rules={**deepcopy(VALID_STOPPING_RULES), "max_attempts": 5},
    )
    db.add(v2)
    db.flush()

    reloaded_v1 = db.get(Playbook, ("pb_versioned", 1))
    assert reloaded_v1.steps_graph == original_graph
    assert reloaded_v1.stopping_rules["max_attempts"] == 3
    assert db.get(Playbook, ("pb_versioned", 2)).stopping_rules["max_attempts"] == 5


def test_orm_update_of_playbook_rejected(db, make_playbook):
    pb = make_playbook()
    pb.trigger_condition = {"changed": True}
    with pytest.raises(AppendOnlyViolation):
        db.flush()


def test_orm_delete_of_playbook_rejected(db, make_playbook):
    pb = make_playbook()
    db.delete(pb)
    with pytest.raises(AppendOnlyViolation):
        db.flush()


def test_raw_update_blocked_by_db_trigger(db, make_playbook):
    pb = make_playbook()
    with pytest.raises(DBAPIError):
        db.execute(
            text("UPDATE playbook SET trigger_condition = '{}'::jsonb WHERE playbook_id = :p"),
            {"p": pb.playbook_id},
        )


def test_raw_delete_blocked_by_db_trigger(db, make_playbook):
    pb = make_playbook()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM playbook WHERE playbook_id = :p"), {"p": pb.playbook_id})


def test_version_must_be_positive(db):
    db.add(PlaybookIdentity(playbook_id="pb_zero"))
    db.flush()
    db.add(
        Playbook(
            playbook_id="pb_zero",
            version=0,
            leg_type=LegType.PAYMENT_DEGRADATION,
            steps_graph=deepcopy(VALID_STEPS_GRAPH),
            stopping_rules=deepcopy(VALID_STOPPING_RULES),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_playbook_requires_identity_row(db):
    db.add(
        Playbook(
            playbook_id="pb_no_identity",
            version=1,
            leg_type=LegType.PAYMENT_DEGRADATION,
            steps_graph=deepcopy(VALID_STEPS_GRAPH),
            stopping_rules=deepcopy(VALID_STOPPING_RULES),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_playbook_has_no_updated_at(engine):
    from sqlalchemy import inspect

    cols = {c["name"] for c in inspect(engine).get_columns("playbook")}
    assert "updated_at" not in cols
    assert "merchant_id" not in cols  # global


def test_playbook_and_identity_are_global_scope(db, make_merchant):
    scope = TenantScope(db, make_merchant().merchant_id)
    with pytest.raises(NonTenantModelError):
        scope.select(Playbook)
    with pytest.raises(NonTenantModelError):
        scope.select(PlaybookIdentity)


def test_identity_deletion_blocked_while_versions_exist(db, make_playbook):
    make_playbook(playbook_id="pb_locked")
    identity = db.get(PlaybookIdentity, "pb_locked")
    db.delete(identity)
    with pytest.raises(IntegrityError):
        db.flush()
