"""Module 4 — version pinning (Blueprint §2.4 / D-021 / D-024).

A run pins the exact version it started on; publishing a newer version never
alters it, and effective rules resolve against the pinned version.
"""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select

from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import CaseStatus, LegType
from torque.models import Playbook, PlaybookRun
from torque.policy import activate_case, resolve_effective_stopping_rules, seed_catalog
from torque.policy import catalog as C


def _case(make_case):
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value,
        diagnosis_confidence=0.9,
        context={"gateway": "razorpay", "decline_code": "insufficient_funds"},
    )


def test_run_pins_latest_version_at_creation(db, make_case):
    seed_catalog(db)
    case = _case(make_case)
    activate_case(db, case_id=case.case_id)
    run = db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).one()
    assert run.playbook_version == 1


def test_new_version_selected_for_new_runs_only(db, make_case, make_merchant, make_counterparty):
    seed_catalog(db)
    m, cp = make_merchant(), make_counterparty()

    case1 = make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value,
        diagnosis_confidence=0.9, context={"gateway": "razorpay"},
    )
    activate_case(db, case_id=case1.case_id)
    run1 = db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case1.case_id)).one()
    assert run1.playbook_version == 1

    # Publish version 2 of the same playbook.
    base = db.get(Playbook, (C.PLAYBOOK_NSF_RETRY, 1))
    db.add(
        Playbook(
            playbook_id=C.PLAYBOOK_NSF_RETRY,
            version=2,
            leg_type=base.leg_type,
            mandate_type=base.mandate_type,
            steps_graph=deepcopy(base.steps_graph),
            stopping_rules={**deepcopy(base.stopping_rules), "max_attempts": 2},
        )
    )
    db.flush()

    # The in-flight run is untouched…
    db.refresh(run1)
    assert run1.playbook_version == 1
    # …and a fresh case picks up version 2.
    case2 = make_case(
        merchant=m, counterparty=make_counterparty(), leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PLAYBOOK_ACTIVE,
        root_cause_code=RootCauseCode.ISSUER_SOFT_DECLINE_NSF.value,
        diagnosis_confidence=0.9, context={"gateway": "razorpay"},
    )
    activate_case(db, case_id=case2.case_id)
    run2 = db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case2.case_id)).one()
    assert run2.playbook_version == 2


def test_effective_rules_use_pinned_version(db, make_case):
    seed_catalog(db)
    case = _case(make_case)
    activate_case(db, case_id=case.case_id)
    run = db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).one()

    # Publish a v2 with different rules; the pinned run still resolves v1's rules.
    # (escalation_ceiling lowered with max_attempts to keep v2 a valid playbook —
    # Module 6 §6.3 enforces escalation_ceiling <= max_attempts at save time.)
    base = db.get(Playbook, (C.PLAYBOOK_NSF_RETRY, 1))
    db.add(
        Playbook(
            playbook_id=C.PLAYBOOK_NSF_RETRY, version=2, leg_type=base.leg_type,
            mandate_type=base.mandate_type, steps_graph=deepcopy(base.steps_graph),
            stopping_rules={
                **deepcopy(base.stopping_rules),
                "max_attempts": 1,
                "escalation_ceiling": 1,
            },
        )
    )
    db.flush()

    rules = resolve_effective_stopping_rules(db, run)
    assert rules.max_attempts == base.stopping_rules["max_attempts"]  # v1, not v2
