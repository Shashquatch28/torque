"""Blueprint Section 3 - `Action` schema: FKs, nullable run_id, coherence
CHECKs, tenant scoping."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from torque.db.scoped import TenantScope
from torque.enums import ActionOutcome, ActionType, Actor, BlockReason
from torque.events import Attribution, write_action_and_event
from torque.exceptions import CrossTenantWriteError
from torque.models import Action


def _bare_action(case, **kw):
    return Action(
        merchant_id=kw.pop("merchant_id", case.merchant_id),
        primary_case_id=kw.pop("primary_case_id", case.case_id),
        run_id=kw.pop("run_id", None),
        action_type=kw.pop("action_type", ActionType.SEND_EMAIL),
        outcome=kw.pop("outcome", ActionOutcome.SUCCESS),
        executed_at=kw.pop("executed_at", datetime.now(UTC)),
        **kw,
    )


def test_run_id_nullable(db, make_action):
    action = make_action(run=None)
    db.refresh(action)
    assert action.run_id is None


def test_run_id_fk_enforced_when_set(db, make_case):
    case = make_case()
    action = _bare_action(case, run_id=uuid.uuid4())
    with pytest.raises(IntegrityError):
        write_action_and_event(db, action=action, actor=Actor.SYSTEM)


def test_primary_case_fk_enforced(db, make_case):
    case = make_case()
    action = _bare_action(case, primary_case_id=uuid.uuid4())
    # guard also needs the ActionCase primary to match; the FK fires first.
    with pytest.raises(IntegrityError):
        write_action_and_event(
            db,
            action=action,
            actor=Actor.SYSTEM,
            attributions=[Attribution(action.primary_case_id, True, Decimal("1.00000"))],
        )


def test_action_type_enum_enforced(db, make_case):
    case = make_case()
    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO action (merchant_id, primary_case_id, action_type, outcome) "
                "VALUES (:m, :c, 'BOGUS', 'SUCCESS')"
            ),
            {"m": case.merchant_id, "c": case.case_id},
        )


# --- coherence: outcome <-> block_reason ------------------------------


def test_blocked_requires_block_reason(db, make_case):
    case = make_case()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO action (merchant_id, primary_case_id, action_type, outcome) "
                "VALUES (:m, :c, 'SEND_WHATSAPP', 'BLOCKED_BY_GUARDRAIL')"
            ),
            {"m": case.merchant_id, "c": case.case_id},
        )


def test_non_blocked_forbids_block_reason(db, make_case):
    case = make_case()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO action "
                "(merchant_id, primary_case_id, action_type, outcome, block_reason, executed_at) "
                "VALUES (:m, :c, 'SEND_WHATSAPP', 'SUCCESS', 'QUIET_HOURS', now())"
            ),
            {"m": case.merchant_id, "c": case.case_id},
        )


# --- coherence: outcome <-> executed_at ----------------------------


def test_blocked_forbids_executed_at(db, make_case):
    case = make_case()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO action "
                "(merchant_id, primary_case_id, action_type, outcome, block_reason, executed_at) "
                "VALUES (:m, :c, 'SEND_WHATSAPP', 'BLOCKED_BY_GUARDRAIL', 'QUIET_HOURS', now())"
            ),
            {"m": case.merchant_id, "c": case.case_id},
        )


def test_non_blocked_requires_executed_at(db, make_case):
    case = make_case()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO action (merchant_id, primary_case_id, action_type, outcome) "
                "VALUES (:m, :c, 'SEND_WHATSAPP', 'NO_RESPONSE')"
            ),
            {"m": case.merchant_id, "c": case.case_id},
        )


def test_blocked_action_persists_via_writer(db, make_action):
    action = make_action(outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL)
    db.refresh(action)
    assert action.executed_at is None
    assert action.block_reason is BlockReason.QUIET_HOURS


# --- cost -----------------------------------------------------------


def test_cost_non_negative_check(db, make_case):
    case = make_case()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO action "
                "(merchant_id, primary_case_id, action_type, outcome, executed_at, cost) "
                "VALUES (:m, :c, 'SEND_SMS', 'SUCCESS', now(), -0.01)"
            ),
            {"m": case.merchant_id, "c": case.case_id},
        )


def test_cost_and_channel_nullable(db, make_action):
    action = make_action(action_type=ActionType.RETRY_PAYMENT, channel=None, cost=None)
    db.refresh(action)
    assert action.cost is None
    assert action.channel is None


# --- tenant scoping ---------------------------------------------


def test_tenant_scope_stamps_merchant_id(db, make_case):
    case = make_case()
    scope = TenantScope(db, case.merchant_id)
    action = Action(
        action_id=uuid.uuid4(),
        primary_case_id=case.case_id,
        action_type=ActionType.SEND_EMAIL,
        outcome=ActionOutcome.SUCCESS,
        executed_at=datetime.now(UTC),
    )
    scope.add(action)  # stamps merchant_id
    assert action.merchant_id == case.merchant_id
    db.expunge(action)  # bare Action — don't let a later flush trip the guard


def test_tenant_scope_rejects_cross_tenant_action(db, make_merchant, make_case):
    case = make_case()
    other = TenantScope(db, make_merchant().merchant_id)
    with pytest.raises(CrossTenantWriteError):
        other.add(_bare_action(case))


def test_no_merged_case_ids_column(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("action")}
    assert "merged_case_ids" not in cols
    assert "merchant_id" in cols
