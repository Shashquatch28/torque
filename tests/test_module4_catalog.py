"""Module 4 — playbook catalog (Blueprint §4.1).

Every required playbook exists, maps to the correct root cause, seeds through the
save-time validator, and re-seeds idempotently. No unintended mappings.
"""

from __future__ import annotations

from sqlalchemy import func, select

from torque.diagnosis.root_causes import VALID_BY_LEG, RootCauseCode
from torque.enums import LegType, MandateType
from torque.models import Playbook, PlaybookIdentity
from torque.policy import catalog as C
from torque.policy import seed_catalog, select_playbook_id

RC = RootCauseCode

EXPECTED_IDS = {
    C.PLAYBOOK_NSF_RETRY,
    C.PLAYBOOK_GENERIC_SOFT_RETRY,
    C.PLAYBOOK_REQUEST_NEW_INSTRUMENT,
    C.PLAYBOOK_SUGGEST_UPI_INTENT,
    C.PLAYBOOK_GENERIC_CART_NUDGE,
    C.PLAYBOOK_SUBSCRIPTION_RETRY_CARD,
    C.PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY,
    C.PLAYBOOK_SUBSCRIPTION_RETRY_NACH,
    C.PLAYBOOK_REQUEST_MANDATE_RENEWAL,
    C.PLAYBOOK_B2B_LOW_RISK_DUNNING,
    C.PLAYBOOK_B2B_HIGH_RISK_DUNNING,
}


def test_catalog_has_exactly_the_eleven_blueprint_playbooks():
    assert {e.playbook_id for e in C.CATALOG} == EXPECTED_IDS
    assert len(C.CATALOG) == 11


def test_seed_inserts_all_playbooks_as_version_1(db):
    created = seed_catalog(db)
    assert created == 11
    for pid in EXPECTED_IDS:
        assert db.get(PlaybookIdentity, pid) is not None
        pb = db.get(Playbook, (pid, 1))
        assert pb is not None
        assert pb.version == 1


def test_seed_is_idempotent(db):
    assert seed_catalog(db) == 11
    assert seed_catalog(db) == 0  # re-seed creates nothing
    # exactly one version per playbook — never forks version 2
    total = db.scalar(select(func.count()).select_from(Playbook))
    assert total == 11


def test_upi_autopay_playbook_respects_ceiling(db):
    seed_catalog(db)
    pb = db.get(Playbook, (C.PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY, 1))
    assert pb.mandate_type is MandateType.UPI_AUTOPAY
    assert pb.stopping_rules["max_attempts"] <= 3


def test_subscription_retry_playbooks_carry_mandate_discriminator(db):
    seed_catalog(db)
    card = db.get(Playbook, (C.PLAYBOOK_SUBSCRIPTION_RETRY_CARD, 1))
    nach = db.get(Playbook, (C.PLAYBOOK_SUBSCRIPTION_RETRY_NACH, 1))
    assert card.mandate_type is MandateType.CARD
    assert nach.mandate_type is MandateType.NACH


def test_every_catalog_playbook_maps_from_a_valid_root_cause():
    """Each catalog playbook is the selection target of at least one legal
    (leg, root_cause[, mandate]) combination — nothing is dead in the catalog."""
    reachable: set[str] = set()
    for leg, causes in VALID_BY_LEG.items():
        for cause in causes:
            for mt in (None, MandateType.CARD, MandateType.UPI_AUTOPAY, MandateType.NACH):
                pid = select_playbook_id(
                    leg_type=leg, root_cause_code=cause.value, mandate_type=mt
                )
                if pid is not None:
                    reachable.add(pid)
    assert reachable == EXPECTED_IDS


def test_leg_types_are_correct(db):
    seed_catalog(db)
    pd = db.get(Playbook, (C.PLAYBOOK_NSF_RETRY, 1))
    co = db.get(Playbook, (C.PLAYBOOK_SUGGEST_UPI_INTENT, 1))
    b2b = db.get(Playbook, (C.PLAYBOOK_B2B_HIGH_RISK_DUNNING, 1))
    assert pd.leg_type is LegType.PAYMENT_DEGRADATION
    assert co.leg_type is LegType.CHECKOUT_ABANDONMENT
    assert b2b.leg_type is LegType.B2B_RECEIVABLE
