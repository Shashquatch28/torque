"""Blueprint Section 2.3 - `write_action_and_event` writes the Action, its
ActionCase attribution row(s), and the correlated CaseEvent in ONE transaction;
the `before_flush` guard structurally enforces it (intentional deviation)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from torque.enums import ActionOutcome, ActionType, Actor, CaseEventType
from torque.events import Attribution, append_case_event, atomic, write_action_and_event
from torque.exceptions import (
    ActionAtomicityError,
    ActionCaseInvariantError,
    PayloadValidationError,
)
from torque.models import Action, ActionCase, CaseEvent


def _count(db, model, **filt):
    stmt = select(func.count()).select_from(model)
    for k, v in filt.items():
        stmt = stmt.where(getattr(model, k) == v)
    return db.scalar(stmt)


def _new_action(case, *, outcome=ActionOutcome.SUCCESS, **kw):
    blocked = outcome is ActionOutcome.BLOCKED_BY_GUARDRAIL
    return Action(
        action_id=uuid.uuid4(),
        merchant_id=case.merchant_id,
        primary_case_id=case.case_id,
        action_type=kw.pop("action_type", ActionType.SEND_WHATSAPP),
        channel=kw.pop("channel", "whatsapp"),
        outcome=outcome,
        executed_at=None if blocked else datetime.now(UTC),
        block_reason=kw.pop("block_reason", None),
        **kw,
    )


# --- happy path -----------------------------------------------------


def test_single_case_writes_action_actioncase_and_event(db, make_case):
    case = make_case()
    action = write_action_and_event(
        db, action=_new_action(case), actor=Actor.SYSTEM
    )
    db.flush()

    acs = db.scalars(
        select(ActionCase).where(ActionCase.action_id == action.action_id)
    ).all()
    assert len(acs) == 1
    assert acs[0].is_primary is True
    assert acs[0].case_id == case.case_id
    assert acs[0].credit_weight == Decimal("1.00000")
    assert acs[0].merchant_id == case.merchant_id

    ce = db.scalars(
        select(CaseEvent).where(CaseEvent.case_id == case.case_id)
    ).all()[-1]
    assert ce.event_type is CaseEventType.ACTION_EXECUTED
    assert ce.payload["action_id"] == str(action.action_id)


def test_blocked_outcome_writes_action_blocked_event(db, make_case):
    from torque.enums import BlockReason

    case = make_case()
    action = write_action_and_event(
        db,
        action=_new_action(
            case, outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL, block_reason=BlockReason.QUIET_HOURS
        ),
        actor=Actor.SYSTEM,
    )
    db.flush()
    ce = db.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .order_by(CaseEvent.event_seq_id.desc())
    ).first()
    assert ce.event_type is CaseEventType.ACTION_BLOCKED
    assert ce.payload["action_id"] == str(action.action_id)
    assert ce.payload["block_reason"] == "QUIET_HOURS"


def test_multi_case_split(db, make_merchant, make_counterparty, make_case):
    m = make_merchant()
    cp = make_counterparty()
    a = make_case(merchant=m, counterparty=cp)
    b = make_case(merchant=m, counterparty=cp)

    action = write_action_and_event(
        db,
        action=_new_action(a),
        actor=Actor.SYSTEM,
        attributions=[
            Attribution(a.case_id, True, Decimal("0.60000")),
            Attribution(b.case_id, False, Decimal("0.40000")),
        ],
    )
    db.flush()
    acs = db.scalars(
        select(ActionCase).where(ActionCase.action_id == action.action_id)
    ).all()
    assert {ac.case_id for ac in acs} == {a.case_id, b.case_id}
    assert sum(ac.credit_weight for ac in acs) == Decimal("1.00000")


# --- rollback -----------------------------------------------------


def test_bad_payload_rolls_back_everything(db, make_case, monkeypatch):
    case = make_case()
    before_a = _count(db, Action)
    before_ce = _count(db, CaseEvent)

    # force an invalid payload by stubbing the event builder
    import torque.events.case_event_writer as w

    monkeypatch.setattr(w, "_event_for", lambda action: (CaseEventType.ACTION_EXECUTED, {"bad": 1}))
    with pytest.raises(PayloadValidationError):
        write_action_and_event(db, action=_new_action(case), actor=Actor.SYSTEM)

    assert _count(db, Action) == before_a
    assert _count(db, CaseEvent) == before_ce


def test_error_after_action_insert_rolls_back(db, make_case):
    case = make_case()
    before_a = _count(db, Action)
    with pytest.raises(RuntimeError):
        with atomic(db):
            action = _new_action(case)
            db.add(action)
            db.add(
                ActionCase(
                    action_id=action.action_id,
                    case_id=case.case_id,
                    merchant_id=case.merchant_id,
                    is_primary=True,
                    credit_weight=Decimal("1.00000"),
                )
            )
            append_case_event(
                db,
                case_id=case.case_id,
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
            db.flush()
            raise RuntimeError("boom after inserts")
    assert _count(db, Action) == before_a


# --- guard backstop -------------------------------------------


def test_bare_action_without_event_rejected(db, make_case):
    case = make_case()
    action = _new_action(case)
    db.add(action)
    db.add(
        ActionCase(
            action_id=action.action_id,
            case_id=case.case_id,
            merchant_id=case.merchant_id,
            is_primary=True,
            credit_weight=Decimal("1.00000"),
        )
    )
    with pytest.raises(ActionAtomicityError):
        db.flush()


def test_action_without_actioncase_rejected(db, make_case):
    case = make_case()
    action = _new_action(case)
    db.add(action)
    append_case_event(
        db,
        case_id=case.case_id,
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


def test_wrong_event_type_for_outcome_rejected(db, make_case):
    """A non-blocked Action paired with an ACTION_BLOCKED event fails."""
    case = make_case()
    action = _new_action(case, outcome=ActionOutcome.SUCCESS)
    db.add(action)
    db.add(
        ActionCase(
            action_id=action.action_id,
            case_id=case.case_id,
            merchant_id=case.merchant_id,
            is_primary=True,
            credit_weight=Decimal("1.00000"),
        )
    )
    append_case_event(
        db,
        case_id=case.case_id,
        event_type=CaseEventType.ACTION_BLOCKED,
        payload={
            "action_id": str(action.action_id),
            "action_type": "SEND_WHATSAPP",
            "block_reason": "QUIET_HOURS",
        },
        actor=Actor.SYSTEM,
    )
    with pytest.raises(ActionAtomicityError):
        db.flush()


# --- explicit correlation with multiple Actions for one case in one flush ---


def test_two_actions_same_case_correlated_by_payload_action_id(db, make_case):
    case = make_case()
    a1 = _new_action(case)
    a2 = _new_action(case)
    for a in (a1, a2):
        db.add(a)
        db.add(
            ActionCase(
                action_id=a.action_id,
                case_id=case.case_id,
                merchant_id=case.merchant_id,
                is_primary=True,
                credit_weight=Decimal("1.00000"),
            )
        )
        append_case_event(
            db,
            case_id=case.case_id,
            event_type=CaseEventType.ACTION_EXECUTED,
            payload={
                "action_id": str(a.action_id),
                "action_type": "SEND_WHATSAPP",
                "channel": "whatsapp",
                "outcome": "SUCCESS",
                "cost": None,
            },
            actor=Actor.SYSTEM,
        )
    db.flush()  # both correlate correctly -> no error
    assert _count(db, Action, primary_case_id=case.case_id) == 2


def test_count_matching_is_not_enough_wrong_action_id_rejected(db, make_case):
    """Two Actions + two ACTION_EXECUTED events for one case, but a2's event
    carries a1's action_id -> a2 has no correlated event -> rejected."""
    case = make_case()
    a1 = _new_action(case)
    a2 = _new_action(case)
    for a, payload_aid in ((a1, a1.action_id), (a2, a1.action_id)):  # a2 -> wrong id
        db.add(a)
        db.add(
            ActionCase(
                action_id=a.action_id,
                case_id=case.case_id,
                merchant_id=case.merchant_id,
                is_primary=True,
                credit_weight=Decimal("1.00000"),
            )
        )
        append_case_event(
            db,
            case_id=case.case_id,
            event_type=CaseEventType.ACTION_EXECUTED,
            payload={
                "action_id": str(payload_aid),
                "action_type": "SEND_WHATSAPP",
                "channel": "whatsapp",
                "outcome": "SUCCESS",
                "cost": None,
            },
            actor=Actor.SYSTEM,
        )
    with pytest.raises(ActionAtomicityError) as exc:
        db.flush()
    assert str(a2.action_id) in str(exc.value)
