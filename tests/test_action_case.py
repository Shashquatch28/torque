"""Blueprint Section 3 / Section 5 - `ActionCase` attribution invariants:
Σ credit_weight == 1.00000 (exact Decimal), exactly one is_primary, primary
matches Action.primary_case_id, same-flush completeness, tenant scoping."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from torque.db.scoped import TenantScope
from torque.enums import ActionOutcome, ActionType, Actor
from torque.events import Attribution, write_action_and_event
from torque.exceptions import ActionCaseInvariantError, CrossTenantWriteError
from torque.models import Action, ActionCase


def _action(case):
    return Action(
        action_id=uuid.uuid4(),
        merchant_id=case.merchant_id,
        primary_case_id=case.case_id,
        action_type=ActionType.SEND_WHATSAPP,
        channel="whatsapp",
        outcome=ActionOutcome.SUCCESS,
        executed_at=datetime.now(UTC),
    )


def _attr(case_id, is_primary, w):
    return Attribution(case_id, is_primary, Decimal(w))


# --- accept -----------------------------------------------------------


def test_single_row_weight_one(db, make_action):
    action = make_action()
    acs = db.query(ActionCase).filter_by(action_id=action.action_id).all()
    assert len(acs) == 1 and acs[0].credit_weight == Decimal("1.00000")


def test_three_rows_sum_to_one(db, make_merchant, make_counterparty, make_case):
    m, cp = make_merchant(), make_counterparty()
    a, b, c = (make_case(merchant=m, counterparty=cp) for _ in range(3))
    write_action_and_event(
        db,
        action=_action(a),
        actor=Actor.SYSTEM,
        attributions=[
            _attr(a.case_id, True, "0.50000"),
            _attr(b.case_id, False, "0.30000"),
            _attr(c.case_id, False, "0.20000"),
        ],
    )
    db.flush()


def test_decimal_exactness(db, make_merchant, make_counterparty, make_case):
    # 0.1 + 0.2 drifts in float but is exact in Decimal
    m, cp = make_merchant(), make_counterparty()
    a, b, c = (make_case(merchant=m, counterparty=cp) for _ in range(3))
    write_action_and_event(
        db,
        action=_action(a),
        actor=Actor.SYSTEM,
        attributions=[
            _attr(a.case_id, True, "0.10000"),
            _attr(b.case_id, False, "0.20000"),
            _attr(c.case_id, False, "0.70000"),
        ],
    )
    db.flush()


# --- reject: Σ != 1 -----------------------------------------------


def test_sum_below_one_rejected(db, make_merchant, make_counterparty, make_case):
    m, cp = make_merchant(), make_counterparty()
    a, b = make_case(merchant=m, counterparty=cp), make_case(merchant=m, counterparty=cp)
    with pytest.raises(ActionCaseInvariantError):
        write_action_and_event(
            db,
            action=_action(a),
            actor=Actor.SYSTEM,
            attributions=[_attr(a.case_id, True, "0.5"), _attr(b.case_id, False, "0.4")],
        )


def test_sum_above_one_rejected(db, make_merchant, make_counterparty, make_case):
    m, cp = make_merchant(), make_counterparty()
    a, b = make_case(merchant=m, counterparty=cp), make_case(merchant=m, counterparty=cp)
    with pytest.raises(ActionCaseInvariantError):
        write_action_and_event(
            db,
            action=_action(a),
            actor=Actor.SYSTEM,
            attributions=[_attr(a.case_id, True, "0.7"), _attr(b.case_id, False, "0.4")],
        )


# --- reject: is_primary -----------------------------------------


def test_two_primaries_rejected(db, make_merchant, make_counterparty, make_case):
    m, cp = make_merchant(), make_counterparty()
    a, b = make_case(merchant=m, counterparty=cp), make_case(merchant=m, counterparty=cp)
    with pytest.raises(ActionCaseInvariantError):
        write_action_and_event(
            db,
            action=_action(a),
            actor=Actor.SYSTEM,
            attributions=[_attr(a.case_id, True, "0.5"), _attr(b.case_id, True, "0.5")],
        )


def test_zero_primaries_rejected(db, make_merchant, make_counterparty, make_case):
    m, cp = make_merchant(), make_counterparty()
    a, b = make_case(merchant=m, counterparty=cp), make_case(merchant=m, counterparty=cp)
    with pytest.raises(ActionCaseInvariantError):
        write_action_and_event(
            db,
            action=_action(a),
            actor=Actor.SYSTEM,
            attributions=[_attr(a.case_id, False, "0.5"), _attr(b.case_id, False, "0.5")],
        )


def test_primary_must_match_action_primary_case_id(db, make_merchant, make_counterparty, make_case):
    m, cp = make_merchant(), make_counterparty()
    a, b = make_case(merchant=m, counterparty=cp), make_case(merchant=m, counterparty=cp)
    with pytest.raises(ActionCaseInvariantError):
        write_action_and_event(
            db,
            action=_action(a),  # primary_case_id = a
            actor=Actor.SYSTEM,
            attributions=[_attr(a.case_id, False, "0.5"), _attr(b.case_id, True, "0.5")],
        )


# --- same-flush completeness -----------------------------------


def test_partial_actioncase_set_rejected(db, make_merchant, make_counterparty, make_case):
    from torque.enums import CaseEventType
    from torque.events import append_case_event

    m, cp = make_merchant(), make_counterparty()
    a = make_case(merchant=m, counterparty=cp)
    action = _action(a)
    db.add(action)
    db.add(
        ActionCase(
            action_id=action.action_id,
            case_id=a.case_id,
            merchant_id=m.merchant_id,
            is_primary=True,
            credit_weight=Decimal("0.60000"),  # only part of a 0.6/0.4 split
        )
    )
    append_case_event(
        db,
        case_id=a.case_id,
        event_type=CaseEventType.ACTION_EXECUTED,
        payload={
            "action_id": str(action.action_id),
            "action_type": "SEND_WHATSAPP",
            "channel": "whatsapp",
            "outcome": "SUCCESS",
            "cost": None,
        },
        actor=Actor.SYSTEM,
    )
    with pytest.raises(ActionCaseInvariantError):
        db.flush()


# --- DB constraints -------------------------------------------


@pytest.mark.parametrize("bad", ["-0.10000", "1.50000"])
def test_credit_weight_range_check(db, make_merchant, make_counterparty, make_case, bad):
    from sqlalchemy import text

    m, cp = make_merchant(), make_counterparty()
    a, b = make_case(merchant=m, counterparty=cp), make_case(merchant=m, counterparty=cp)
    action = make_action_fixture(db, a)
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO action_case "
                "(action_id, case_id, merchant_id, is_primary, credit_weight) "
                "VALUES (:a, :c, :m, false, :w)"
            ),
            {"a": action, "c": b.case_id, "m": m.merchant_id, "w": bad},
        )


def test_composite_pk_dedup(db, make_action):
    action = make_action()
    db.add(
        ActionCase(
            action_id=action.action_id,
            case_id=action.primary_case_id,
            merchant_id=action.merchant_id,
            is_primary=False,
            credit_weight=Decimal("0.00000"),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


# --- re-weight (Module 7 style) ------------------------------


def test_reweight_keeping_sum_ok(db, make_merchant, make_counterparty, make_case):
    m, cp = make_merchant(), make_counterparty()
    a, b = make_case(merchant=m, counterparty=cp), make_case(merchant=m, counterparty=cp)
    action = write_action_and_event(
        db,
        action=_action(a),
        actor=Actor.SYSTEM,
        attributions=[_attr(a.case_id, True, "0.5"), _attr(b.case_id, False, "0.5")],
    )
    db.flush()

    rows = {
        ac.case_id: ac
        for ac in db.query(ActionCase).filter_by(action_id=action.action_id).all()
    }
    rows[a.case_id].credit_weight = Decimal("0.70000")
    rows[b.case_id].credit_weight = Decimal("0.30000")
    db.flush()  # still sums to 1 -> ok


def test_reweight_breaking_sum_rejected(db, make_merchant, make_counterparty, make_case):
    m, cp = make_merchant(), make_counterparty()
    a, b = make_case(merchant=m, counterparty=cp), make_case(merchant=m, counterparty=cp)
    action = write_action_and_event(
        db,
        action=_action(a),
        actor=Actor.SYSTEM,
        attributions=[_attr(a.case_id, True, "0.5"), _attr(b.case_id, False, "0.5")],
    )
    db.flush()

    row = db.query(ActionCase).filter_by(action_id=action.action_id, case_id=a.case_id).one()
    row.credit_weight = Decimal("0.90000")
    with pytest.raises(ActionCaseInvariantError):
        db.flush()


# --- tenant scoping ---------------------------------------


def test_tenant_scoped(db, make_action, make_case):
    action = make_action()
    other = TenantScope(db, make_case().merchant_id)
    with pytest.raises(CrossTenantWriteError):
        other.add(
            ActionCase(
                action_id=action.action_id,
                case_id=action.primary_case_id,
                merchant_id=action.merchant_id,
                is_primary=False,
                credit_weight=Decimal("0"),
            )
        )


def make_action_fixture(db, case):
    """Persist an Action (single valid ActionCase + correlated event); return id."""
    action = write_action_and_event(
        db,
        action=Action(
            merchant_id=case.merchant_id,
            primary_case_id=case.case_id,
            action_type=ActionType.SEND_SMS,
            channel="sms",
            outcome=ActionOutcome.SUCCESS,
            executed_at=datetime.now(UTC),
        ),
        actor=Actor.SYSTEM,
    )
    db.flush()
    return action.action_id
