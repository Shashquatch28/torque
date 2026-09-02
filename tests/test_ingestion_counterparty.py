"""Milestone 7b — `torque.ingestion.identity.resolve_counterparty`."""

from __future__ import annotations

from sqlalchemy import select

from torque.ingestion.identity import resolve_counterparty
from torque.models import Counterparty, MerchantCounterparty


def test_matches_existing_by_phone(db, make_merchant, make_counterparty):
    m = make_merchant()
    existing = make_counterparty(phone="+919700000001", email="a@test.dev")
    cp, mc = resolve_counterparty(
        db, merchant_id=m.merchant_id, phone="+919700000001", email="different@test.dev"
    )
    assert cp.counterparty_id == existing.counterparty_id
    assert mc.merchant_id == m.merchant_id


def test_falls_back_to_email_when_phone_absent_or_unmatched(db, make_merchant, make_counterparty):
    m = make_merchant()
    existing = make_counterparty(phone="+919700000002", email="match@test.dev")
    cp, _ = resolve_counterparty(
        db, merchant_id=m.merchant_id, phone=None, email="match@test.dev"
    )
    assert cp.counterparty_id == existing.counterparty_id


def test_creates_a_new_identity_with_safe_consent_defaults(db, make_merchant):
    m = make_merchant()
    cp, mc = resolve_counterparty(
        db, merchant_id=m.merchant_id, phone="+919700000003", email="brand@new.dev"
    )
    assert cp.phone == "+919700000003"
    assert cp.email == "brand@new.dev"
    assert cp.name is None
    assert cp.payment_failure_nudge_consent is False
    assert cp.whatsapp_opt_in is False
    assert mc.counterparty_id == cp.counterparty_id


def test_merchant_counterparty_is_isolated_per_merchant(db, make_merchant):
    m1, m2 = make_merchant(), make_merchant()
    cp1, mc1 = resolve_counterparty(
        db, merchant_id=m1.merchant_id, phone="+919700000004", email=None
    )
    cp2, mc2 = resolve_counterparty(
        db, merchant_id=m2.merchant_id, phone="+919700000004", email=None
    )
    assert cp1.counterparty_id == cp2.counterparty_id  # same global identity
    assert mc1.id != mc2.id
    assert {mc1.merchant_id, mc2.merchant_id} == {m1.merchant_id, m2.merchant_id}
    rows = db.scalars(
        select(MerchantCounterparty).where(
            MerchantCounterparty.counterparty_id == cp1.counterparty_id
        )
    ).all()
    assert len(rows) == 2


def test_existing_merchant_counterparty_is_reused(db, make_merchant):
    m = make_merchant()
    _, mc_a = resolve_counterparty(
        db, merchant_id=m.merchant_id, phone="+919700000005", email=None
    )
    _, mc_b = resolve_counterparty(
        db, merchant_id=m.merchant_id, phone="+919700000005", email=None
    )
    assert mc_a.id == mc_b.id
    assert len(db.scalars(select(Counterparty)).all()) == 1
