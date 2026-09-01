"""Blueprint Section 3 - `PromiseToPay`: surrogate PK, `captured_via` UNIQUE
(0..1 per Action), the PENDING -> KEPT / BROKEN lifecycle enforced by
`torque.promises` AND the `before_flush` guard, tenant isolation, no
`on_broken` column."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from torque.db.scoped import TenantScope
from torque.enums import PromiseStatus
from torque.exceptions import CrossTenantWriteError, PromiseTransitionError
from torque.models import PromiseToPay
from torque.promises import (
    PROMISE_TRANSITIONS,
    TERMINAL_PROMISE_STATUSES,
    assert_promise_transition,
    transition_promise,
)

DUE = date(2026, 10, 15)


def _promise(case, action, **kw):
    return PromiseToPay(
        merchant_id=kw.pop("merchant_id", case.merchant_id),
        case_id=kw.pop("case_id", case.case_id),
        captured_via=kw.pop("captured_via", action.action_id),
        promised_amount=kw.pop("promised_amount", Decimal("1000.00")),
        promised_date=kw.pop("promised_date", DUE),
        **kw,
    )


# --- identity / PK -----------------------------------------------------


def test_promise_id_is_uuid_pk(db, make_promise):
    p = make_promise()
    assert isinstance(p.promise_id, uuid.UUID)


def test_merchant_fk_enforced(db, make_case, make_action):
    case = make_case()
    db.add(_promise(case, make_action(case=case), merchant_id="acc_ghost"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_case_fk_enforced(db, make_case, make_action):
    case = make_case()
    db.add(_promise(case, make_action(case=case), case_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        db.flush()


def test_captured_via_fk_enforced(db, make_case, make_action):
    case = make_case()
    db.add(_promise(case, make_action(case=case), captured_via=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        db.flush()


# --- captured_via UNIQUE (0..1 per Action) ------------------------


def test_second_promise_for_same_action_rejected(db, make_case, make_action):
    case = make_case()
    action = make_action(case=case)
    db.add(_promise(case, action))
    db.flush()
    db.add(_promise(case, action))
    with pytest.raises(IntegrityError):
        db.flush()


# --- column constraints --------------------------------------------


def test_promised_amount_non_negative(db, make_case, make_action):
    case = make_case()
    db.add(_promise(case, make_action(case=case), promised_amount=Decimal("-1")))
    with pytest.raises(IntegrityError):
        db.flush()


def test_promised_date_required(db, make_case, make_action):
    case = make_case()
    db.add(_promise(case, make_action(case=case), promised_date=None))
    with pytest.raises(IntegrityError):
        db.flush()


def test_default_status_is_pending(db, make_promise):
    p = make_promise()
    db.refresh(p)
    assert p.status is PromiseStatus.PENDING


# --- transition helper -------------------------------------------


def test_transition_graph_matches_spec():
    assert PROMISE_TRANSITIONS == {
        PromiseStatus.PENDING: {PromiseStatus.KEPT, PromiseStatus.BROKEN},
        PromiseStatus.KEPT: set(),
        PromiseStatus.BROKEN: set(),
    }
    assert TERMINAL_PROMISE_STATUSES == frozenset(
        {PromiseStatus.KEPT, PromiseStatus.BROKEN}
    )


@pytest.mark.parametrize("target", [PromiseStatus.KEPT, PromiseStatus.BROKEN])
def test_legal_transition_succeeds(db, make_promise, target):
    p = make_promise()
    transition_promise(p, target)
    db.flush()
    db.refresh(p)
    assert p.status is target


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (PromiseStatus.KEPT, PromiseStatus.BROKEN),
        (PromiseStatus.KEPT, PromiseStatus.PENDING),
        (PromiseStatus.BROKEN, PromiseStatus.KEPT),
        (PromiseStatus.BROKEN, PromiseStatus.PENDING),
        (PromiseStatus.PENDING, PromiseStatus.PENDING),
    ],
)
def test_illegal_transition_rejected_by_helper(start, target):
    with pytest.raises(PromiseTransitionError):
        assert_promise_transition(start, target)


def test_terminal_states_cannot_transition(db, make_promise):
    p = make_promise()
    transition_promise(p, PromiseStatus.KEPT)
    db.flush()
    with pytest.raises(PromiseTransitionError):
        transition_promise(p, PromiseStatus.BROKEN)


# --- before_flush guard ----------------------------------------


def test_new_promise_must_be_pending(db, make_case, make_action):
    case = make_case()
    db.add(_promise(case, make_action(case=case), status=PromiseStatus.KEPT))
    with pytest.raises(PromiseTransitionError):
        db.flush()


def test_direct_illegal_status_mutation_caught_by_guard(db, make_promise):
    p = make_promise()
    transition_promise(p, PromiseStatus.KEPT)
    db.flush()

    # bypass the helper - poke the attribute directly
    p.status = PromiseStatus.BROKEN
    with pytest.raises(PromiseTransitionError):
        db.flush()


def test_direct_revert_to_pending_caught_by_guard(db, make_promise):
    p = make_promise()
    transition_promise(p, PromiseStatus.BROKEN)
    db.flush()

    p.status = PromiseStatus.PENDING
    with pytest.raises(PromiseTransitionError):
        db.flush()


def test_direct_legal_mutation_allowed_by_guard(db, make_promise):
    # the guard rejects only ILLEGAL transitions; a direct PENDING -> KEPT is fine
    p = make_promise()
    p.status = PromiseStatus.KEPT
    db.flush()
    db.refresh(p)
    assert p.status is PromiseStatus.KEPT


# --- tenant isolation / schema -------------------------------


def test_tenant_scoped(db, make_case, make_action, make_merchant):
    case = make_case()
    action = make_action(case=case)
    scope = TenantScope(db, case.merchant_id)
    p = PromiseToPay(
        case_id=case.case_id,
        captured_via=action.action_id,
        promised_amount=Decimal("10.00"),
        promised_date=DUE,
    )
    scope.add(p)
    assert p.merchant_id == case.merchant_id
    db.flush()

    case2 = make_case()
    action2 = make_action(case=case2)
    other = TenantScope(db, make_merchant().merchant_id)
    with pytest.raises(CrossTenantWriteError):
        other.add(_promise(case2, action2))


def test_no_on_broken_column(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("promise_to_pay")}
    assert "on_broken" not in cols
    assert "merchant_id" in cols
