"""Phase 7 — `torque.ai.shadow.features` correctness: deterministic
generation, schema validation, PII exclusion, tenant isolation, and — the
top priority per the Phase 7 task — target-leakage prevention.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tests.ai_shadow_cases import (
    add_b2b_invoice,
    diagnose,
    make_terminal_diagnosed_case,
    receive_network_directive,
    set_counterparty_relationship,
)
from torque.ai.exceptions import FeatureExtractionError
from torque.ai.shadow.features import build_shadow_dataset, extract_features
from torque.ai.shadow.schemas import ShadowFeatureVector
from torque.enums import CaseStatus, LegType, MacTier, MandateType

# --- deterministic generation + schema -----------------------------------


def test_extract_features_is_deterministic(db, make_case):
    case = make_terminal_diagnosed_case(db, make_case, status=CaseStatus.RECOVERED)
    first = extract_features(db, merchant_id=case.merchant_id, case=case)
    second = extract_features(db, merchant_id=case.merchant_id, case=case)
    assert first == second


def test_shadow_feature_vector_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ShadowFeatureVector(
            case_id="c1",
            merchant_id="m1",
            feature_schema_version="shadow-features-v1",
            as_of=datetime.now(UTC),
            leg_type="PAYMENT_DEGRADATION",
            root_cause_code="X",
            diagnosis_confidence=0.5,
            amount_at_risk="100.00",
            days_since_failure=1.0,
            promise_keeping_rate=None,
            risk_score=None,
            mandate_type=None,
            network_directive_tier=None,
            not_a_real_field="oops",
        )


def test_shadow_feature_vector_has_no_post_outcome_fields():
    """Structural leakage guard: the DTO itself must not even be able to
    carry `recovery_type`/`recovered_amount`/`recovery_score`/
    `escalation_resolution`/`closed_at` — the exact post-outcome fields
    `torque.ai.schemas.CaseSnapshot` documents as excluded from any future
    shadow-ML feature path."""
    forbidden = {
        "recovery_type",
        "recovered_amount",
        "recovery_score",
        "recovery_score_breakdown",
        "escalation_resolution",
        "closed_at",
        "status",
    }
    assert forbidden.isdisjoint(ShadowFeatureVector.model_fields.keys())


def test_extract_features_raises_for_undiagnosed_case(db, make_case):
    case = make_case(status=CaseStatus.DETECTED)
    with pytest.raises(FeatureExtractionError):
        extract_features(db, merchant_id=case.merchant_id, case=case)


# --- PII exclusion ---------------------------------------------------------


def test_features_never_carry_counterparty_pii(db, make_case, make_counterparty):
    cp = make_counterparty(name="Rohan Secret Name", phone="+919812340000", email="rohan@x.com")
    case = make_terminal_diagnosed_case(
        db, make_case, status=CaseStatus.RECOVERED, counterparty=cp
    )
    features = extract_features(db, merchant_id=case.merchant_id, case=case)
    blob = features.model_dump_json()
    assert "Rohan Secret Name" not in blob
    assert "+919812340000" not in blob
    assert "rohan@x.com" not in blob


# --- tenant isolation -------------------------------------------------------


def test_extract_features_rejects_merchant_mismatch(db, make_case, make_merchant):
    case = make_terminal_diagnosed_case(db, make_case, status=CaseStatus.RECOVERED)
    other = make_merchant()
    with pytest.raises(ValueError, match="not"):
        extract_features(db, merchant_id=other.merchant_id, case=case)


def test_build_shadow_dataset_never_crosses_tenants(db, make_case, make_merchant):
    merchant_a = make_merchant()
    merchant_b = make_merchant()
    make_terminal_diagnosed_case(
        db, make_case, status=CaseStatus.RECOVERED, merchant=merchant_a
    )
    make_terminal_diagnosed_case(
        db, make_case, status=CaseStatus.RECOVERED, merchant=merchant_b
    )

    dataset_a = build_shadow_dataset(db, merchant_id=merchant_a.merchant_id)
    dataset_b = build_shadow_dataset(db, merchant_id=merchant_b.merchant_id)

    assert len(dataset_a) == 1
    assert len(dataset_b) == 1
    assert dataset_a[0].features.case_id != dataset_b[0].features.case_id
    assert all(ex.features.merchant_id == merchant_a.merchant_id for ex in dataset_a)
    assert all(ex.features.merchant_id == merchant_b.merchant_id for ex in dataset_b)


def test_build_shadow_dataset_excludes_undiagnosed_and_open_cases(db, make_case, make_merchant):
    merchant = make_merchant()
    diagnosed = make_terminal_diagnosed_case(
        db, make_case, status=CaseStatus.RECOVERED, merchant=merchant
    )
    make_case(status=CaseStatus.DETECTED, merchant=merchant)  # same merchant, no diagnosis
    open_but_diagnosed = make_case(status=CaseStatus.PLAYBOOK_ACTIVE, merchant=merchant)
    diagnose(db, open_but_diagnosed)  # diagnosed but not terminal -> still excluded

    dataset = build_shadow_dataset(db, merchant_id=merchant.merchant_id)
    case_ids = {ex.features.case_id for ex in dataset}
    assert str(diagnosed.case_id) in case_ids
    assert str(open_but_diagnosed.case_id) not in case_ids
    assert len(dataset) == 1


# --- target-leakage prevention ---------------------------------------------


def test_b2b_amount_at_risk_uses_original_invoice_total_not_live_case_column(db, make_case):
    """The live `RevenueLeakCase.amount_at_risk` for a fully-recovered B2B
    case has already been decremented to (near) zero by Module 7 (INV-55) —
    using it directly would leak the outcome. The extractor must instead sum
    `B2BInvoice.original_amount`, which Module 7 never mutates."""
    case = make_terminal_diagnosed_case(
        db,
        make_case,
        status=CaseStatus.RECOVERED,
        leg=LegType.B2B_RECEIVABLE,
        amount_at_risk=0,  # post-recovery live value — deliberately near-zero
    )
    add_b2b_invoice(
        db,
        case,
        original_amount=5000,
        outstanding_amount=0,
        due_date=(datetime.now(UTC) - timedelta(days=20)).date(),
    )
    add_b2b_invoice(
        db,
        case,
        original_amount=2500,
        outstanding_amount=0,
        due_date=(datetime.now(UTC) - timedelta(days=15)).date(),
    )

    features = extract_features(db, merchant_id=case.merchant_id, case=case)
    assert float(features.amount_at_risk) == pytest.approx(7500.0)


def test_non_b2b_amount_at_risk_reads_the_case_column_directly(db, make_case):
    case = make_terminal_diagnosed_case(
        db, make_case, status=CaseStatus.RECOVERED, amount_at_risk=1234
    )
    features = extract_features(db, merchant_id=case.merchant_id, case=case)
    assert float(features.amount_at_risk) == pytest.approx(1234.0)


def test_network_directive_tier_is_reconstructed_as_of_diagnosis_not_final_value(
    db, make_case
):
    """A tier that tightens AFTER diagnosis (but before the case closes)
    must not appear in the feature vector — only tiers received on or
    before the diagnosis cutoff count."""
    case = make_terminal_diagnosed_case(
        db, make_case, status=CaseStatus.EXHAUSTED, diagnosed_hours_after_open=1.0
    )
    diagnosed_at = case.opened_at + timedelta(hours=1)

    # A TIER_2 directive received well before diagnosis -> should be seen.
    receive_network_directive(
        db, case, tier=MacTier.TIER_2_CAPPED_RETRY, at=case.opened_at + timedelta(minutes=10)
    )
    # A stricter TIER_1 directive received AFTER diagnosis -> must be excluded.
    receive_network_directive(
        db, case, tier=MacTier.TIER_1_HARD_STOP, at=diagnosed_at + timedelta(hours=2)
    )

    features = extract_features(db, merchant_id=case.merchant_id, case=case)
    assert features.network_directive_tier == MacTier.TIER_2_CAPPED_RETRY.value


def test_network_directive_tier_is_none_when_no_directive_received_by_cutoff(db, make_case):
    case = make_terminal_diagnosed_case(db, make_case, status=CaseStatus.RECOVERED)
    features = extract_features(db, merchant_id=case.merchant_id, case=case)
    assert features.network_directive_tier is None


def test_days_since_failure_is_measured_to_diagnosis_cutoff_not_to_now_or_closure(
    db, make_case
):
    """`days_since_failure` must reflect case-age-at-diagnosis, not total
    time-to-closure (which would encode how the case eventually ended)."""
    case = make_terminal_diagnosed_case(
        db,
        make_case,
        status=CaseStatus.RECOVERED,
        opened_days_ago=30.0,  # the case has been closed for a long time
        diagnosed_hours_after_open=48.0,  # but diagnosis itself was quick
    )
    features = extract_features(db, merchant_id=case.merchant_id, case=case)
    assert features.days_since_failure == pytest.approx(2.0, abs=0.01)


# --- feature-field derivations ----------------------------------------------


def test_mandate_type_present_only_for_subscription_failure(db, make_case):
    sub_case = make_terminal_diagnosed_case(
        db,
        make_case,
        status=CaseStatus.RECOVERED,
        leg=LegType.SUBSCRIPTION_FAILURE,
        context={
            "mandate_id": "mandate_1",
            "mandate_type": MandateType.UPI_AUTOPAY.value,
            "billing_cycle": "3",
            "subscription_id": "sub_1",
        },
    )
    payment_case = make_terminal_diagnosed_case(db, make_case, status=CaseStatus.RECOVERED)

    sub_features = extract_features(db, merchant_id=sub_case.merchant_id, case=sub_case)
    payment_features = extract_features(
        db, merchant_id=payment_case.merchant_id, case=payment_case
    )

    assert sub_features.mandate_type == MandateType.UPI_AUTOPAY.value
    assert payment_features.mandate_type is None


def test_counterparty_relationship_fields_read_when_present_and_none_when_absent(
    db, make_case
):
    with_relationship = make_terminal_diagnosed_case(db, make_case, status=CaseStatus.RECOVERED)
    set_counterparty_relationship(
        db, with_relationship, promise_keeping_rate=0.75, risk_score=0.2
    )
    without_relationship = make_terminal_diagnosed_case(db, make_case, status=CaseStatus.RECOVERED)

    with_features = extract_features(
        db, merchant_id=with_relationship.merchant_id, case=with_relationship
    )
    without_features = extract_features(
        db, merchant_id=without_relationship.merchant_id, case=without_relationship
    )

    assert with_features.promise_keeping_rate == pytest.approx(0.75)
    assert with_features.risk_score == pytest.approx(0.2)
    assert without_features.promise_keeping_rate is None
    assert without_features.risk_score is None


def test_root_cause_code_and_diagnosis_confidence_are_read_verbatim(db, make_case):
    case = make_terminal_diagnosed_case(
        db,
        make_case,
        status=CaseStatus.RECOVERED,
        root_cause_code="ISSUER_HARD_DECLINE",
        diagnosis_confidence=0.42,
    )
    features = extract_features(db, merchant_id=case.merchant_id, case=case)
    assert features.root_cause_code == "ISSUER_HARD_DECLINE"
    assert features.diagnosis_confidence == pytest.approx(0.42)
    assert features.leg_type == LegType.PAYMENT_DEGRADATION.value
