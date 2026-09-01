"""Blueprint Section 3 / Section 2.4 - `PlaybookRun`: tenant-scoped, version-pinned,
single `active_step_id` pointer, no `step_history`."""

from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.conftest import VALID_STEPS_GRAPH, VALID_STOPPING_RULES
from torque.db.scoped import TenantScope
from torque.enums import LegType, PlaybookRunStatus
from torque.exceptions import CrossTenantWriteError
from torque.models import Playbook, PlaybookRun


def test_defaults_and_nullable_pointer(db, make_playbook_run):
    run = make_playbook_run()
    db.refresh(run)
    assert run.status is PlaybookRunStatus.RUNNING
    assert run.active_step_id is None


def test_status_enum_enforced(db, make_case, make_playbook):
    case = make_case()
    pb = make_playbook()
    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO playbook_run "
                "(merchant_id, case_id, playbook_id, playbook_version, status) "
                "VALUES (:m, :c, :p, :v, 'BOGUS')"
            ),
            {"m": case.merchant_id, "c": case.case_id, "p": pb.playbook_id, "v": pb.version},
        )


def test_case_fk_enforced(db, make_playbook):
    pb = make_playbook()
    db.add(
        PlaybookRun(
            merchant_id="acc_ghost",
            case_id=uuid.uuid4(),
            playbook_id=pb.playbook_id,
            playbook_version=pb.version,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_composite_playbook_fk_enforced(db, make_case):
    case = make_case()
    db.add(
        PlaybookRun(
            merchant_id=case.merchant_id,
            case_id=case.case_id,
            playbook_id="pb_nope",
            playbook_version=99,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_wrong_version_rejected_by_composite_fk(db, make_case, make_playbook):
    case = make_case()
    pb = make_playbook()  # version 1 only
    db.add(
        PlaybookRun(
            merchant_id=case.merchant_id,
            case_id=case.case_id,
            playbook_id=pb.playbook_id,
            playbook_version=2,  # does not exist
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_version_pin_survives_new_version(db, make_case, make_playbook):
    case = make_case()
    make_playbook(playbook_id="pb_pin", version=1)
    run = PlaybookRun(
        merchant_id=case.merchant_id,
        case_id=case.case_id,
        playbook_id="pb_pin",
        playbook_version=1,
    )
    db.add(run)
    db.flush()

    db.add(
        Playbook(
            playbook_id="pb_pin",
            version=2,
            leg_type=LegType.PAYMENT_DEGRADATION,
            steps_graph=deepcopy(VALID_STEPS_GRAPH),
            stopping_rules={**deepcopy(VALID_STOPPING_RULES), "max_attempts": 9},
        )
    )
    db.flush()

    db.refresh(run)
    assert run.playbook_version == 1
    pinned = db.get(Playbook, ("pb_pin", 1))
    assert pinned.stopping_rules["max_attempts"] == 3


def test_tenant_scoped(db, make_case, make_playbook):
    case = make_case()
    pb = make_playbook()
    scope = TenantScope(db, case.merchant_id)
    run = PlaybookRun(
        case_id=case.case_id, playbook_id=pb.playbook_id, playbook_version=pb.version
    )
    scope.add(run)
    db.flush()
    assert run.merchant_id == case.merchant_id

    other = TenantScope(db, make_case().merchant_id)
    with pytest.raises(CrossTenantWriteError):
        other.add(
            PlaybookRun(
                merchant_id=case.merchant_id,
                case_id=case.case_id,
                playbook_id=pb.playbook_id,
                playbook_version=pb.version,
            )
        )


def test_playbook_run_has_no_step_history(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("playbook_run")}
    assert "step_history" not in cols
    assert "merchant_id" in cols
