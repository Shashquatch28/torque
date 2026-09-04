"""Phase 7 — `torque.ai.shadow.scoring.score_case` correctness: prediction
schema, tenant isolation, feature-extraction propagation, and — the top
structural requirement — proof it never mutates authoritative state.
"""

from __future__ import annotations

import uuid

import pytest

from tests.ai_shadow_cases import make_terminal_diagnosed_case
from torque.ai.exceptions import EvidenceNotFoundError, FeatureExtractionError
from torque.ai.shadow.model import LogisticRegressionShadowModel
from torque.ai.shadow.schemas import SHADOW_DISCLAIMER
from torque.ai.shadow.scoring import score_case
from torque.enums import CaseStatus


def _fitted_model(db, make_case, merchant):
    for i in range(6):
        make_terminal_diagnosed_case(
            db,
            make_case,
            status=CaseStatus.RECOVERED if i < 4 else CaseStatus.EXHAUSTED,
            merchant=merchant,
        )
    from torque.ai.shadow.features import build_shadow_dataset

    model = LogisticRegressionShadowModel()
    model.fit(build_shadow_dataset(db, merchant_id=merchant.merchant_id))
    return model


def test_score_case_returns_a_fully_populated_shadow_prediction(db, make_case, make_merchant):
    merchant = make_merchant()
    model = _fitted_model(db, make_case, merchant)
    case = make_case(status=CaseStatus.PLAYBOOK_ACTIVE, merchant=merchant)
    from tests.ai_shadow_cases import diagnose

    diagnose(db, case)

    prediction = score_case(
        db,
        merchant_id=merchant.merchant_id,
        case_id=case.case_id,
        model=model,
        n_training_cases=model.n_training_examples,
    )

    assert prediction.case_id == str(case.case_id)
    assert prediction.merchant_id == merchant.merchant_id
    assert prediction.model_id == "sklearn-logistic-regression-v1"
    assert 0.0 <= prediction.predicted_recovery_probability <= 1.0
    assert prediction.predicted_label == (prediction.predicted_recovery_probability >= 0.5)
    assert prediction.n_training_cases == 6
    assert prediction.disclaimer == SHADOW_DISCLAIMER
    assert "NOT USED FOR DECISIONS" in prediction.disclaimer


def test_score_case_can_score_an_open_but_diagnosed_case(db, make_case, make_merchant):
    """Scoring is not limited to terminal cases — an open, already-diagnosed
    case is exactly the realistic use case for a shadow prediction."""
    merchant = make_merchant()
    model = _fitted_model(db, make_case, merchant)
    from tests.ai_shadow_cases import diagnose

    open_case = make_case(status=CaseStatus.PLAYBOOK_ACTIVE, merchant=merchant)
    diagnose(db, open_case)

    prediction = score_case(
        db,
        merchant_id=merchant.merchant_id,
        case_id=open_case.case_id,
        model=model,
        n_training_cases=6,
    )
    assert prediction.case_id == str(open_case.case_id)


def test_score_case_rejects_unknown_case(db, make_case, make_merchant):
    merchant = make_merchant()
    model = _fitted_model(db, make_case, merchant)
    with pytest.raises(EvidenceNotFoundError):
        score_case(
            db,
            merchant_id=merchant.merchant_id,
            case_id=uuid.uuid4(),
            model=model,
            n_training_cases=6,
        )


def test_score_case_rejects_cross_tenant_case(db, make_case, make_merchant):
    merchant_a = make_merchant()
    merchant_b = make_merchant()
    model = _fitted_model(db, make_case, merchant_a)

    case_for_b = make_case(status=CaseStatus.PLAYBOOK_ACTIVE, merchant=merchant_b)
    from tests.ai_shadow_cases import diagnose

    diagnose(db, case_for_b)

    with pytest.raises(EvidenceNotFoundError):
        score_case(
            db,
            merchant_id=merchant_a.merchant_id,
            case_id=case_for_b.case_id,
            model=model,
            n_training_cases=6,
        )


def test_score_case_raises_for_undiagnosed_case(db, make_case, make_merchant):
    merchant = make_merchant()
    model = _fitted_model(db, make_case, merchant)
    undiagnosed = make_case(status=CaseStatus.DETECTED, merchant=merchant)

    with pytest.raises(FeatureExtractionError):
        score_case(
            db,
            merchant_id=merchant.merchant_id,
            case_id=undiagnosed.case_id,
            model=model,
            n_training_cases=6,
        )


def test_score_case_writes_nothing_to_the_database(db, make_case, make_merchant):
    merchant = make_merchant()
    model = _fitted_model(db, make_case, merchant)
    from tests.ai_shadow_cases import diagnose

    case = make_case(status=CaseStatus.PLAYBOOK_ACTIVE, merchant=merchant)
    diagnose(db, case)
    db.flush()

    before_new, before_dirty, before_deleted = len(db.new), len(db.dirty), len(db.deleted)
    score_case(
        db,
        merchant_id=merchant.merchant_id,
        case_id=case.case_id,
        model=model,
        n_training_cases=6,
    )
    assert len(db.new) == before_new
    assert len(db.dirty) == before_dirty
    assert len(db.deleted) == before_deleted
