"""Blueprint Section 4.2 / decision A - `MerchantPlaybookConfig`: tenant-scoped
override, validated at flush against the latest `Playbook` version, with UPI
AutoPay defense-in-depth."""

from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import VALID_STOPPING_RULES
from torque.db.scoped import TenantScope
from torque.enums import LegType, MandateType
from torque.exceptions import (
    CrossTenantWriteError,
    PlaybookNotFoundError,
    PlaybookValidationError,
)
from torque.models import MerchantPlaybookConfig, PlaybookIdentity


def _cfg(merchant, playbook, **kw):
    return MerchantPlaybookConfig(
        merchant_id=merchant.merchant_id,
        playbook_id=playbook.playbook_id,
        **kw,
    )


def test_null_override_persists_and_defaults_enabled(db, make_merchant, make_playbook):
    m, pb = make_merchant(), make_playbook()
    cfg = _cfg(m, pb)
    db.add(cfg)
    db.flush()
    db.refresh(cfg)
    assert cfg.stopping_rules_override is None
    assert cfg.enabled is True


def test_valid_partial_override_accepted(db, make_merchant, make_playbook):
    m, pb = make_merchant(), make_playbook()
    cfg = _cfg(
        m,
        pb,
        stopping_rules_override={"max_attempts": 5, "allowed_hours": {"end": "20:00"}},
    )
    db.add(cfg)
    db.flush()
    assert cfg.stopping_rules_override["max_attempts"] == 5


def test_upi_override_over_ceiling_rejected_at_flush(db, make_merchant, make_playbook):
    m = make_merchant()
    upi_pb = make_playbook(
        playbook_id="pb_upi_std",
        leg_type=LegType.SUBSCRIPTION_FAILURE,
        mandate_type=MandateType.UPI_AUTOPAY,
        stopping_rules={**deepcopy(VALID_STOPPING_RULES), "max_attempts": 3},
    )
    db.add(_cfg(m, upi_pb, stopping_rules_override={"max_attempts": 10}))
    with pytest.raises(PlaybookValidationError):
        db.flush()


def test_malformed_override_rejected_at_flush(db, make_merchant, make_playbook):
    m, pb = make_merchant(), make_playbook()
    db.add(_cfg(m, pb, stopping_rules_override={"max_attempts": 5, "bogus": 1}))
    with pytest.raises(PlaybookValidationError):
        db.flush()


def test_editing_an_override_revalidates(db, make_merchant, make_playbook):
    m = make_merchant()
    upi_pb = make_playbook(
        playbook_id="pb_upi_edit",
        leg_type=LegType.SUBSCRIPTION_FAILURE,
        mandate_type=MandateType.UPI_AUTOPAY,
        stopping_rules={**deepcopy(VALID_STOPPING_RULES), "max_attempts": 2},
    )
    cfg = _cfg(m, upi_pb, stopping_rules_override={"max_attempts": 3})
    db.add(cfg)
    db.flush()

    cfg.stopping_rules_override = {"max_attempts": 9}
    with pytest.raises(PlaybookValidationError):
        db.flush()


def test_config_for_playbook_without_version_rejected(db, make_merchant):
    m = make_merchant()
    db.add(PlaybookIdentity(playbook_id="pb_bare"))
    db.flush()
    db.add(MerchantPlaybookConfig(merchant_id=m.merchant_id, playbook_id="pb_bare"))
    with pytest.raises(PlaybookNotFoundError):
        db.flush()


def test_unknown_playbook_id_rejected_by_guard(db, make_merchant):
    # The guard resolves the latest version before the DB FK check is reached,
    # so a nonexistent playbook_id surfaces as PlaybookNotFoundError.
    m = make_merchant()
    db.add(MerchantPlaybookConfig(merchant_id=m.merchant_id, playbook_id="pb_ghost"))
    with pytest.raises(PlaybookNotFoundError):
        db.flush()


def test_unknown_playbook_id_rejected_by_db_fk(db, make_merchant):
    # Belt-and-suspenders: the DB FK itself rejects an unknown id on a raw insert
    # that bypasses the ORM guard.
    from sqlalchemy import text

    m = make_merchant()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO merchant_playbook_config (merchant_id, playbook_id) "
                "VALUES (:m, 'pb_ghost')"
            ),
            {"m": m.merchant_id},
        )


def test_unique_per_merchant_per_playbook(db, make_merchant, make_playbook):
    m, pb = make_merchant(), make_playbook()
    db.add(_cfg(m, pb))
    db.flush()
    db.add(_cfg(m, pb))
    with pytest.raises(IntegrityError):
        db.flush()


def test_same_playbook_different_merchants_ok(db, make_merchant, make_playbook):
    m1, m2 = make_merchant(), make_merchant()
    pb = make_playbook()
    db.add(_cfg(m1, pb))
    db.add(_cfg(m2, pb))
    db.flush()


def test_tenant_scoped(db, make_merchant, make_playbook):
    m1, m2 = make_merchant(), make_merchant()
    pb = make_playbook()
    scope1 = TenantScope(db, m1.merchant_id)
    cfg = MerchantPlaybookConfig(playbook_id=pb.playbook_id)
    scope1.add(cfg)
    db.flush()
    assert cfg.merchant_id == m1.merchant_id

    scope2 = TenantScope(db, m2.merchant_id)
    with pytest.raises(CrossTenantWriteError):
        scope2.add(_cfg(m1, pb))
