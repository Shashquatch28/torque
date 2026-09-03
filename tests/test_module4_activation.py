"""Module 4 — `PlaybookRun` instantiation & escalation (Blueprint §4).

Covers run creation for a PLAYBOOK_ACTIVE case, initial active step, idempotency,
the no-playbook / disabled → ESCALATED_TO_HUMAN routes, eligibility gating
(superseded / wrong state), tenant isolation, and atomic rollback.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import CaseStatus, LegType, PlaybookRunStatus
from torque.models import CaseEvent, MerchantPlaybookConfig, PlaybookRun
from torque.policy import ActivationOutcome, activate_case, seed_catalog
from torque.policy import catalog as C

RC = RootCauseCode


@pytest.fixture()
def seeded(db):
    seed_catalog(db)
    return db


def _pd_case(make_case, *, cause=RC.ISSUER_SOFT_DECLINE_NSF, **kw):
    kw.setdefault("status", CaseStatus.PLAYBOOK_ACTIVE)
    kw.setdefault("context", {"gateway": "razorpay", "decline_code": "insufficient_funds"})
    return make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code=cause.value,
        diagnosis_confidence=0.9,
        **kw,
    )


def _sub_case(make_case, *, cause, mandate_type, **kw):
    kw.setdefault("status", CaseStatus.PLAYBOOK_ACTIVE)
    kw.setdefault(
        "context",
        {
            "mandate_id": "m4mandate",
            "mandate_type": mandate_type.value,
            "billing_cycle": "1",
            "subscription_id": "sub4",
        },
    )
    return make_case(
        leg=LegType.SUBSCRIPTION_FAILURE,
        root_cause_code=cause.value,
        diagnosis_confidence=0.9,
        **kw,
    )


def _runs_for(db, case):
    return db.scalars(select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)).all()


# --- run creation ------------------------------------------------------------


def test_creates_pinned_run_at_entry_step(seeded, make_case):
    case = _pd_case(make_case)
    out = activate_case(seeded, case_id=case.case_id)

    assert out is ActivationOutcome.RUN_CREATED
    runs = _runs_for(seeded, case)
    assert len(runs) == 1
    run = runs[0]
    assert run.playbook_id == C.PLAYBOOK_NSF_RETRY
    assert run.playbook_version == 1
    assert run.merchant_id == case.merchant_id
    assert run.status is PlaybookRunStatus.RUNNING
    assert run.active_step_id == "retry"  # entry node of PLAYBOOK_NSF_RETRY
    # Case stays PLAYBOOK_ACTIVE (Module 3 already put it there); no new status event.
    seeded.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE


def test_subscription_upi_selects_rail_specific_run(seeded, make_case):
    from torque.enums import MandateType

    case = _sub_case(make_case, cause=RC.NSF_SOFT_DECLINE, mandate_type=MandateType.UPI_AUTOPAY)
    activate_case(seeded, case_id=case.case_id)
    run = _runs_for(seeded, case)[0]
    assert run.playbook_id == C.PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY


# --- idempotency -------------------------------------------------------------


def test_second_activation_is_noop(seeded, make_case):
    case = _pd_case(make_case)
    assert activate_case(seeded, case_id=case.case_id) is ActivationOutcome.RUN_CREATED
    assert activate_case(seeded, case_id=case.case_id) is ActivationOutcome.NOOP
    assert len(_runs_for(seeded, case)) == 1  # no duplicate run


def test_paused_run_also_blocks_a_new_run(seeded, make_case):
    case = _pd_case(make_case)
    activate_case(seeded, case_id=case.case_id)
    run = _runs_for(seeded, case)[0]
    run.status = PlaybookRunStatus.PAUSED
    seeded.flush()
    assert activate_case(seeded, case_id=case.case_id) is ActivationOutcome.NOOP


def test_terminal_run_does_not_block_reactivation(seeded, make_case):
    case = _pd_case(make_case)
    activate_case(seeded, case_id=case.case_id)
    run = _runs_for(seeded, case)[0]
    run.status = PlaybookRunStatus.CANCELLED  # terminal
    seeded.flush()
    assert activate_case(seeded, case_id=case.case_id) is ActivationOutcome.RUN_CREATED
    assert len(_runs_for(seeded, case)) == 2


# --- eligibility -------------------------------------------------------------


def test_missing_case_is_noop(seeded):
    assert activate_case(seeded, case_id=uuid.uuid4()) is ActivationOutcome.NOOP


def test_non_playbook_active_case_is_noop(seeded, make_case):
    case = _pd_case(make_case, status=CaseStatus.DIAGNOSING)
    assert activate_case(seeded, case_id=case.case_id) is ActivationOutcome.NOOP
    assert _runs_for(seeded, case) == []


def test_superseded_case_is_noop(seeded, make_case, make_merchant, make_counterparty):
    m, cp = make_merchant(), make_counterparty()
    survivor = _pd_case(make_case, merchant=m, counterparty=cp)
    superseded = _pd_case(make_case, merchant=m, counterparty=cp)
    superseded.superseded_by_case_id = survivor.case_id
    seeded.flush()
    assert activate_case(seeded, case_id=superseded.case_id) is ActivationOutcome.NOOP
    assert _runs_for(seeded, superseded) == []


# --- escalation --------------------------------------------------------------


def test_no_playbook_escalates(seeded, make_case):
    case = _pd_case(make_case, cause=RC.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED)
    out = activate_case(seeded, case_id=case.case_id)
    assert out is ActivationOutcome.ESCALATED_NO_PLAYBOOK
    seeded.refresh(case)
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN
    assert _runs_for(seeded, case) == []
    # the escalation is a normal STATUS_CHANGED (no invented event type)
    ev = seeded.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.case_id)
        .where(CaseEvent.event_type == "STATUS_CHANGED")
    ).all()
    assert any(e.payload["to_status"] == "ESCALATED_TO_HUMAN" for e in ev)


def test_disabled_playbook_escalates(seeded, make_case):
    case = _pd_case(make_case)
    seeded.add(
        MerchantPlaybookConfig(
            merchant_id=case.merchant_id,
            playbook_id=C.PLAYBOOK_NSF_RETRY,
            enabled=False,
        )
    )
    seeded.flush()
    out = activate_case(seeded, case_id=case.case_id)
    assert out is ActivationOutcome.ESCALATED_DISABLED
    seeded.refresh(case)
    assert case.status is CaseStatus.ESCALATED_TO_HUMAN
    assert _runs_for(seeded, case) == []


def test_enabled_config_does_not_block(seeded, make_case):
    case = _pd_case(make_case)
    seeded.add(
        MerchantPlaybookConfig(
            merchant_id=case.merchant_id, playbook_id=C.PLAYBOOK_NSF_RETRY, enabled=True
        )
    )
    seeded.flush()
    assert activate_case(seeded, case_id=case.case_id) is ActivationOutcome.RUN_CREATED


# --- tenant isolation --------------------------------------------------------


def test_disabled_config_of_other_merchant_does_not_affect(seeded, make_case, make_merchant):
    other = make_merchant()
    seeded.add(
        MerchantPlaybookConfig(
            merchant_id=other.merchant_id, playbook_id=C.PLAYBOOK_NSF_RETRY, enabled=False
        )
    )
    seeded.flush()
    case = _pd_case(make_case)  # different merchant
    # Merchant B disabling the playbook must not disable it for merchant A.
    assert activate_case(seeded, case_id=case.case_id) is ActivationOutcome.RUN_CREATED


def test_run_is_tenant_scoped_to_the_case_merchant(seeded, make_case):
    case = _pd_case(make_case)
    activate_case(seeded, case_id=case.case_id)
    run = _runs_for(seeded, case)[0]
    assert run.merchant_id == case.merchant_id


# --- atomicity ---------------------------------------------------------------


def test_activation_failure_rolls_back(seeded, make_case, monkeypatch):
    case = _pd_case(make_case, cause=RC.ISSUER_HARD_DECLINE_FRAUD_SUSPECTED)

    def _boom(*a, **k):
        raise RuntimeError("injected")

    # Fail during the escalate transition.
    monkeypatch.setattr("torque.policy.engine.transition_case", _boom)
    with pytest.raises(RuntimeError, match="injected"):
        activate_case(seeded, case_id=case.case_id)
    seeded.refresh(case)
    assert case.status is CaseStatus.PLAYBOOK_ACTIVE  # unchanged
    n_events = seeded.scalar(
        select(func.count()).select_from(CaseEvent).where(CaseEvent.case_id == case.case_id)
    )
    assert n_events == 0
