"""Blueprint Section 3 - `MerchantWhatsAppTemplate` (WhatsApp gate #2 of 2) and
the pure `approved_template_exists` predicate.

`approval_status` is a Meta-owned free string: the invariant is NOT "status must
be in a known list" - it is exact `== 'APPROVED'` passes, everything else (incl.
future/unmodelled Meta statuses) fails closed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from torque.compliance import WHATSAPP_APPROVED, approved_template_exists
from torque.db.scoped import TenantScope
from torque.enums import LegType, WhatsAppTemplateCategory
from torque.exceptions import CrossTenantWriteError
from torque.models import MerchantWhatsAppTemplate

UTIL = WhatsAppTemplateCategory.UTILITY
MKTG = WhatsAppTemplateCategory.MARKETING


def _tmpl(merchant, **kw):
    return MerchantWhatsAppTemplate(
        template_id=kw.pop("template_id", f"wamtpl_{merchant.merchant_id}_{kw.get('n', 0)}"),
        merchant_id=kw.pop("merchant_id", merchant.merchant_id),
        template_name=kw.pop("template_name", "tmpl"),
        category=kw.pop("category", UTIL),
        approval_status=kw.pop("approval_status", "APPROVED"),
        leg_type=kw.pop("leg_type", LegType.PAYMENT_DEGRADATION),
    )


# --- schema / model --------------------------------------------------------


def test_template_id_pk_uniqueness(db, make_merchant):
    m = make_merchant()
    db.add(_tmpl(m, template_id="wamtpl_dup"))
    db.flush()
    db.add(_tmpl(m, template_id="wamtpl_dup"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_merchant_fk_enforced(db, make_merchant):
    m = make_merchant()
    db.add(_tmpl(m, merchant_id="acc_ghost"))
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize(
    "field", ["template_name", "category", "approval_status", "leg_type"]
)
def test_required_fields_reject_null(db, make_merchant, field):
    m = make_merchant()
    tmpl = _tmpl(m)
    setattr(tmpl, field, None)
    db.add(tmpl)
    with pytest.raises(IntegrityError):
        db.flush()


def test_category_accepts_utility_and_marketing(db, make_wa_template):
    a = make_wa_template(category=UTIL, template_id="wamtpl_u")
    b = make_wa_template(category=MKTG, template_id="wamtpl_m")
    db.refresh(a)
    db.refresh(b)
    assert a.category is UTIL and b.category is MKTG


_INSERT = (
    "INSERT INTO merchant_whatsapp_template "
    "(template_id, merchant_id, template_name, category, approval_status, leg_type) "
    "VALUES (:tid, :m, 'x', :cat, 'APPROVED', :leg)"
)


def test_invalid_category_rejected_at_db(db, make_merchant):
    m = make_merchant()
    with pytest.raises(DBAPIError):
        db.execute(
            text(_INSERT),
            {
                "tid": "wamtpl_badcat",
                "m": m.merchant_id,
                "cat": "AUTHENTICATION",  # deferred category - not in the enum
                "leg": "PAYMENT_DEGRADATION",
            },
        )


def test_invalid_leg_type_rejected_at_db(db, make_merchant):
    m = make_merchant()
    with pytest.raises(DBAPIError):
        db.execute(
            text(_INSERT),
            {
                "tid": "wamtpl_badleg",
                "m": m.merchant_id,
                "cat": "UTILITY",
                "leg": "NOT_A_LEG",
            },
        )


@pytest.mark.parametrize(
    "status",
    ["APPROVED", "PENDING", "REJECTED", "PAUSED", "DISABLED", "IN_APPEAL",
     "LIMIT_EXCEEDED", "SOME_FUTURE_META_STATUS", "approved"],
)
def test_approval_status_is_a_free_string(db, make_wa_template, status):
    t = make_wa_template(approval_status=status, template_id=f"wamtpl_{status}")
    db.refresh(t)
    assert t.approval_status == status


def test_multiple_approved_for_same_merchant_leg_category_coexist(db, make_wa_template):
    m = make_wa_template().merchant_id
    from torque.models import Merchant

    merchant = db.get(Merchant, m)
    make_wa_template(merchant=merchant, template_id="wamtpl_dup_a")
    make_wa_template(merchant=merchant, template_id="wamtpl_dup_b")
    # both APPROVED, same (merchant, PAYMENT_DEGRADATION, UTILITY) -> no error


def test_no_uniqueness_beyond_pk(engine):
    assert inspect(engine).get_unique_constraints("merchant_whatsapp_template") == []


# --- tenant scoping ------------------------------------------------------


def test_tenant_stamping(db, make_merchant):
    m = make_merchant()
    scope = TenantScope(db, m.merchant_id)
    tmpl = MerchantWhatsAppTemplate(
        template_id="wamtpl_scoped",
        template_name="t",
        category=UTIL,
        approval_status="APPROVED",
        leg_type=LegType.PAYMENT_DEGRADATION,
    )
    scope.add(tmpl)
    db.flush()
    assert tmpl.merchant_id == m.merchant_id


def test_cross_tenant_write_fails(db, make_merchant):
    m1, m2 = make_merchant(), make_merchant()
    other = TenantScope(db, m2.merchant_id)
    with pytest.raises(CrossTenantWriteError):
        other.add(_tmpl(m1))


def test_tenant_filtered_reads(db, make_merchant, make_wa_template):
    m1, m2 = make_merchant(), make_merchant()
    make_wa_template(merchant=m1, template_id="wamtpl_m1")
    make_wa_template(merchant=m2, template_id="wamtpl_m2")
    rows = TenantScope(db, m1.merchant_id).all(MerchantWhatsAppTemplate)
    assert [r.merchant_id for r in rows] == [m1.merchant_id]


def test_no_pii_columns(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("merchant_whatsapp_template")}
    assert not ({"name", "phone", "email"} & cols)
    assert "on_broken" not in cols
    assert "counterparty_id" not in cols


# --- approved_template_exists ---------------------------------------


def test_matching_approved_row_true(db, make_wa_template):
    m = make_wa_template().merchant_id
    assert approved_template_exists(
        db, merchant_id=m, leg_type=LegType.PAYMENT_DEGRADATION, category=UTIL
    )


@pytest.mark.parametrize(
    "status", ["PENDING", "REJECTED", "PAUSED", "DISABLED", "SOMETHING_NEW", "approved"]
)
def test_non_approved_status_false(db, make_merchant, make_wa_template, status):
    m = make_merchant()
    make_wa_template(merchant=m, approval_status=status)
    assert not approved_template_exists(
        db, merchant_id=m.merchant_id, leg_type=LegType.PAYMENT_DEGRADATION, category=UTIL
    )


def test_wrong_merchant_false(db, make_merchant, make_wa_template):
    make_wa_template()
    other = make_merchant()
    assert not approved_template_exists(
        db, merchant_id=other.merchant_id, leg_type=LegType.PAYMENT_DEGRADATION, category=UTIL
    )


def test_wrong_leg_false(db, make_wa_template):
    m = make_wa_template(leg_type=LegType.PAYMENT_DEGRADATION).merchant_id
    assert not approved_template_exists(
        db, merchant_id=m, leg_type=LegType.SUBSCRIPTION_FAILURE, category=UTIL
    )


def test_wrong_category_false(db, make_wa_template):
    m = make_wa_template(category=UTIL).merchant_id
    assert not approved_template_exists(
        db, merchant_id=m, leg_type=LegType.PAYMENT_DEGRADATION, category=MKTG
    )


def test_no_row_false(db, make_merchant):
    m = make_merchant()
    assert not approved_template_exists(
        db, merchant_id=m.merchant_id, leg_type=LegType.PAYMENT_DEGRADATION, category=UTIL
    )


def test_multiple_rows_one_approved_true(db, make_merchant, make_wa_template):
    m = make_merchant()
    make_wa_template(merchant=m, approval_status="PENDING", template_id="wamtpl_p")
    make_wa_template(merchant=m, approval_status="REJECTED", template_id="wamtpl_r")
    make_wa_template(merchant=m, approval_status="APPROVED", template_id="wamtpl_a")
    assert approved_template_exists(
        db, merchant_id=m.merchant_id, leg_type=LegType.PAYMENT_DEGRADATION, category=UTIL
    )


def test_multiple_rows_none_approved_false(db, make_merchant, make_wa_template):
    m = make_merchant()
    make_wa_template(merchant=m, approval_status="PENDING", template_id="wamtpl_p2")
    make_wa_template(merchant=m, approval_status="PAUSED", template_id="wamtpl_x2")
    assert not approved_template_exists(
        db, merchant_id=m.merchant_id, leg_type=LegType.PAYMENT_DEGRADATION, category=UTIL
    )


def test_category_accepts_enum_and_string(db, make_wa_template):
    m = make_wa_template(category=UTIL).merchant_id
    assert approved_template_exists(
        db, merchant_id=m, leg_type=LegType.PAYMENT_DEGRADATION, category=UTIL
    )
    assert approved_template_exists(
        db, merchant_id=m, leg_type=LegType.PAYMENT_DEGRADATION, category="UTILITY"
    )


def test_predicate_uses_whatsapp_approved_constant():
    assert WHATSAPP_APPROVED == "APPROVED"
    import inspect as _inspect

    from torque.compliance import whatsapp

    src = _inspect.getsource(whatsapp.approved_template_exists)
    assert "WHATSAPP_APPROVED" in src
    assert '"APPROVED"' not in src and "'APPROVED'" not in src


# --- schema introspection --------------------------------------


def test_gate_index_columns(engine):
    idx = next(
        i
        for i in inspect(engine).get_indexes("merchant_whatsapp_template")
        if i["name"] == "ix_merchant_whatsapp_template_gate"
    )
    assert idx["column_names"] == ["merchant_id", "leg_type", "category"]


def test_approval_status_is_varchar_not_enum(engine):
    col = next(
        c
        for c in inspect(engine).get_columns("merchant_whatsapp_template")
        if c["name"] == "approval_status"
    )
    assert col["type"].__class__.__name__ in {"VARCHAR", "String"}


def test_category_uses_whatsapp_template_category_enum(engine):
    col = next(
        c
        for c in inspect(engine).get_columns("merchant_whatsapp_template")
        if c["name"] == "category"
    )
    assert getattr(col["type"], "name", None) == "whatsapp_template_category"


def test_table_is_tenant_scoped(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("merchant_whatsapp_template")}
    assert "merchant_id" in cols
