"""Module 4 — effective stopping-rules resolution at runtime (Blueprint §4.2 / D-023).

The definition-contract deep-merge is already covered by `test_playbook_*`; here
the focus is the *runtime* resolver reading the merchant override for a live run.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import CaseStatus, LegType
from torque.exceptions import PlaybookValidationError
from torque.models import MerchantPlaybookConfig, PlaybookRun
from torque.policy import activate_case, resolve_effective_stopping_rules, seed_catalog
from torque.policy import catalog as C


def _run_for(db, make_case, merchant, *, playbook_cause=RootCauseCode.ISSUER_SOFT_DECLINE_NSF):
    case = make_case(
        merchant=merchant, leg=LegType.PAYMENT_DEGRADATION, status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code=playbook_cause.value, diagnosis_confidence=0.9,
        context={"gateway": "razorpay"},
    )
    activate_case(db, case_id=case.case_id)
    return db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).one()


def test_no_override_uses_base_rules(db, make_case, make_merchant):
    seed_catalog(db)
    m = make_merchant()
    run = _run_for(db, make_case, m)
    rules = resolve_effective_stopping_rules(db, run)
    base = C.CATALOG_BY_ID[C.PLAYBOOK_NSF_RETRY].stopping_rules
    assert rules.max_attempts == base["max_attempts"]
    assert rules.escalation_ceiling == base["escalation_ceiling"]


def test_scalar_override_replaces(db, make_case, make_merchant):
    seed_catalog(db)
    m = make_merchant()
    db.add(
        MerchantPlaybookConfig(
            merchant_id=m.merchant_id, playbook_id=C.PLAYBOOK_NSF_RETRY,
            stopping_rules_override={"max_attempts": 2},
        )
    )
    db.flush()
    run = _run_for(db, make_case, m)
    assert resolve_effective_stopping_rules(db, run).max_attempts == 2


def test_nested_dict_override_deep_merges(db, make_case, make_merchant):
    seed_catalog(db)
    m = make_merchant()
    db.add(
        MerchantPlaybookConfig(
            merchant_id=m.merchant_id, playbook_id=C.PLAYBOOK_NSF_RETRY,
            stopping_rules_override={"allowed_hours": {"end": "18:00"}},  # start kept from base
        )
    )
    db.flush()
    run = _run_for(db, make_case, m)
    rules = resolve_effective_stopping_rules(db, run)
    assert rules.allowed_hours.start == "09:00"  # from base
    assert rules.allowed_hours.end == "18:00"  # overridden


def test_disabled_config_still_merges_rules_for_existing_run(db, make_case, make_merchant):
    """`enabled` gates availability, not rule resolution (D-023). A run created
    while enabled keeps resolving the override even if the merchant later disables
    the playbook."""
    seed_catalog(db)
    m = make_merchant()
    run = _run_for(db, make_case, m)
    db.add(
        MerchantPlaybookConfig(
            merchant_id=m.merchant_id, playbook_id=C.PLAYBOOK_NSF_RETRY,
            stopping_rules_override={"max_attempts": 2}, enabled=False,
        )
    )
    db.flush()
    assert resolve_effective_stopping_rules(db, run).max_attempts == 2


def test_upi_ceiling_still_rejected_in_override(db, make_merchant):
    """The save-time guard rejects a merchant override that pushes a UPI AutoPay
    playbook past 3 (defense-in-depth remains intact)."""
    seed_catalog(db)
    m = make_merchant()
    with pytest.raises(PlaybookValidationError):
        db.add(
            MerchantPlaybookConfig(
                merchant_id=m.merchant_id,
                playbook_id=C.PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY,
                stopping_rules_override={"max_attempts": 5},
            )
        )
        db.flush()
