"""Blueprint Section 3 - `PaymentLink`: string PK, nullable `action_id`
(externally-originated links), the `paid <-> paid_at` biconditional, tenant
isolation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from torque.db.scoped import TenantScope
from torque.enums import PaymentLinkStatus
from torque.exceptions import CrossTenantWriteError
from torque.models import PaymentLink

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _link(case, **kw):
    return PaymentLink(
        link_id=kw.pop("link_id", f"plink_{uuid.uuid4().hex[:12]}"),
        merchant_id=kw.pop("merchant_id", case.merchant_id),
        action_id=kw.pop("action_id", None),
        case_id=kw.pop("case_id", case.case_id),
        **kw,
    )


# --- PK / FKs -------------------------------------------------------------


def test_link_id_pk_uniqueness(db, make_case):
    case = make_case()
    db.add(_link(case, link_id="plink_dup"))
    db.flush()
    db.add(_link(case, link_id="plink_dup"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_action_id_nullable_via_fixture(db, make_payment_link):
    link = make_payment_link(action=None)  # unattributed / externally-originated link
    db.refresh(link)
    assert link.action_id is None


def test_action_id_nullable_explicit(db, make_case):
    link = _link(make_case(), action_id=None)
    db.add(link)
    db.flush()
    assert link.action_id is None


def test_valid_action_fk_when_supplied(db, make_case, make_action):
    case = make_case()
    action = make_action(case=case)
    link = _link(case, action_id=action.action_id)
    db.add(link)
    db.flush()
    assert link.action_id == action.action_id


def test_unknown_action_fk_rejected(db, make_case):
    link = _link(make_case(), action_id=uuid.uuid4())
    db.add(link)
    with pytest.raises(IntegrityError):
        db.flush()


def test_unknown_case_fk_rejected(db, make_case):
    link = _link(make_case(), case_id=uuid.uuid4())
    db.add(link)
    with pytest.raises(IntegrityError):
        db.flush()


def test_unknown_merchant_fk_rejected(db, make_case):
    link = _link(make_case(), merchant_id="acc_ghost")
    db.add(link)
    with pytest.raises(IntegrityError):
        db.flush()


# --- defaults ------------------------------------------------------------


def test_default_status_is_issued(db, make_case):
    link = _link(make_case())
    db.add(link)
    db.flush()
    db.refresh(link)
    assert link.status is PaymentLinkStatus.ISSUED


def test_default_amount_paid_is_zero(db, make_case):
    link = _link(make_case())
    db.add(link)
    db.flush()
    db.refresh(link)
    assert link.amount_paid == Decimal("0.00")


def test_status_enum_enforced(db, make_case):
    case = make_case()
    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO payment_link (link_id, merchant_id, case_id, status) "
                "VALUES ('plink_bad', :m, :c, 'BOGUS')"
            ),
            {"m": case.merchant_id, "c": case.case_id},
        )


# --- CHECK: amount_paid >= 0 -------------------------------------------


def test_negative_amount_paid_rejected(db, make_case):
    db.add(_link(make_case(), amount_paid=Decimal("-0.01")))
    with pytest.raises(IntegrityError):
        db.flush()


# --- CHECK: (status = 'paid') <-> (paid_at IS NOT NULL) --------------


def test_paid_without_paid_at_rejected(db, make_case):
    db.add(_link(make_case(), status=PaymentLinkStatus.PAID, paid_at=None))
    with pytest.raises(IntegrityError):
        db.flush()


def test_paid_at_with_non_paid_status_rejected(db, make_case):
    db.add(_link(make_case(), status=PaymentLinkStatus.ISSUED, paid_at=NOW))
    with pytest.raises(IntegrityError):
        db.flush()


def test_partially_paid_with_paid_at_rejected(db, make_case):
    # partially_paid is NOT 'paid' -> paid_at must be NULL
    db.add(_link(make_case(), status=PaymentLinkStatus.PARTIALLY_PAID, paid_at=NOW))
    with pytest.raises(IntegrityError):
        db.flush()


def test_valid_paid_state_accepted(db, make_case):
    link = _link(
        make_case(),
        status=PaymentLinkStatus.PAID,
        amount_paid=Decimal("500.00"),
        paid_at=NOW,
    )
    db.add(link)
    db.flush()
    db.refresh(link)
    assert link.status is PaymentLinkStatus.PAID
    assert link.paid_at == NOW


def test_issued_with_null_paid_at_accepted(db, make_case):
    link = _link(make_case(), status=PaymentLinkStatus.ISSUED, paid_at=None)
    db.add(link)
    db.flush()


# --- tenant isolation --------------------------------------------


def test_tenant_scoped(db, make_case, make_merchant):
    case = make_case()
    scope = TenantScope(db, case.merchant_id)
    link = PaymentLink(link_id="plink_scoped", case_id=case.case_id)
    scope.add(link)  # stamps merchant_id
    assert link.merchant_id == case.merchant_id
    db.flush()

    other = TenantScope(db, make_merchant().merchant_id)
    with pytest.raises(CrossTenantWriteError):
        other.add(_link(case))


def test_select_is_merchant_filtered(db, make_case):
    m1_case = make_case()
    m2_case = make_case()
    db.add(_link(m1_case))
    db.add(_link(m2_case))
    db.flush()

    rows = TenantScope(db, m1_case.merchant_id).all(PaymentLink)
    assert len(rows) == 1
    assert rows[0].merchant_id == m1_case.merchant_id


def test_no_pii_columns(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("payment_link")}
    assert not ({"name", "phone", "email"} & cols)
    assert "merchant_id" in cols
