"""Phase 4 — `torque.ai.providers` tests: `LLMProvider` and `MockProvider`.

No database, no network, no API key. Minimal but real
`torque.ai.schemas.CaseEvidence` objects are constructed directly (Pydantic
only) to build prompts and drive `MockProvider`, exactly as
`torque.ai.prompts.build_narrative_prompt` does in production — no giant
hand-rolled mock object standing in for the real schema.

Async: `LLMProvider.structured_generate` is `async def` (see
`torque.ai.providers.base`'s docstring for why). Tests drive it with
`asyncio.run(...)` — stdlib only, no new test dependency (`pytest-asyncio`
was deliberately not added; see `documentation/ai-memory/DECISIONS.md`).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest

from torque.ai.prompts import build_narrative_prompt
from torque.ai.providers.base import LLMProvider
from torque.ai.providers.mock_provider import MockProvider
from torque.ai.schemas import (
    CaseEvidence,
    CaseNarrative,
    CaseSnapshot,
    EvidenceReference,
    TimelineEntry,
)

_FIXED_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _reference(source_type, source_id, case_id, event_seq_id=None):
    return EvidenceReference(
        source_type=source_type,
        source_id=source_id,
        case_id=case_id,
        event_seq_id=event_seq_id,
        timestamp=_FIXED_TS,
    )


def _minimal_evidence(
    case_id: str = "11111111-1111-1111-1111-111111111111",
    *,
    root_cause_code: str | None = "ISSUER_SOFT_DECLINE_NSF",
) -> CaseEvidence:
    snapshot = CaseSnapshot(
        reference=_reference("case", case_id, case_id),
        case_id=case_id,
        leg_type="PAYMENT_DEGRADATION",
        status="DIAGNOSING",
        amount_at_risk="1000.00",
        root_cause_code=root_cause_code,
        root_cause_label="Issuer soft decline" if root_cause_code else None,
        diagnosis_confidence=0.8 if root_cause_code else None,
        network_directive_tier=None,
        opened_at=_FIXED_TS,
        closed_at=None,
        recovery_type=None,
        recovered_amount=None,
        recovery_score=None,
        recovery_score_breakdown=None,
        escalation_resolution=None,
    )
    timeline = [
        TimelineEntry(
            reference=_reference("case_event", "1", case_id, event_seq_id=1),
            event_type="DIAGNOSIS_COMPLETED",
            actor="AGENT",
            timestamp=_FIXED_TS,
            reasoning="Diagnosed as an issuer soft decline.",
            payload={"root_cause_code": root_cause_code},
        )
    ]
    return CaseEvidence(
        case_id=case_id,
        merchant_id="acc_test",
        snapshot=snapshot,
        timeline=timeline,
        actions=[],
        promises=[],
        counterparty_relationship=None,
        evidence_gaps=[] if root_cause_code else ["No diagnosis has been recorded yet."],
        gathered_at=_FIXED_TS,
    )


def _generate(provider, evidence, precedents=None):
    system, user = build_narrative_prompt(evidence, precedents or [])
    return asyncio.run(
        provider.structured_generate(
            system=system, user=user, schema=CaseNarrative, max_tokens=1000, timeout_s=10.0
        )
    )


# --- LLMProvider interface ----------------------------------------------


def test_llm_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


# --- MockProvider: happy path --------------------------------------------


def test_mock_provider_returns_a_valid_case_narrative():
    evidence = _minimal_evidence()
    result = _generate(MockProvider(), evidence)
    assert isinstance(result, CaseNarrative)
    assert result.case_id == evidence.case_id


def test_mock_provider_citations_correspond_to_supplied_evidence():
    evidence = _minimal_evidence()
    result = _generate(MockProvider(), evidence)
    valid_ids = {evidence.snapshot.reference.reference_id} | {
        e.reference.reference_id for e in evidence.timeline
    }
    for citation in result.citations:
        assert citation.evidence_id in valid_ids


def test_mock_provider_id_default_and_custom():
    assert MockProvider().provider_id() == "mock:deterministic-v1"
    assert MockProvider(provider_id="mock:custom").provider_id() == "mock:custom"


def test_mock_provider_is_deterministic():
    evidence = _minimal_evidence()
    first = _generate(MockProvider(), evidence)
    second = _generate(MockProvider(), evidence)
    assert first == second


def test_mock_provider_has_no_network_dependency():
    """Behavioral proxy for "no network call": generation over a minimal
    evidence set completes near-instantly. A real network-backed provider
    would not be sub-100ms reliably; this mock always is."""
    evidence = _minimal_evidence()
    start = time.monotonic()
    _generate(MockProvider(), evidence)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0


def test_mock_provider_no_precedent_case_produces_honest_empty_section():
    evidence = _minimal_evidence()
    result = _generate(MockProvider(), evidence, precedents=[])
    assert result.precedent.found is False
    assert result.precedent.cases == []


def test_mock_provider_missing_diagnosis_produces_a_gap_not_a_guess():
    evidence = _minimal_evidence(root_cause_code=None)
    result = _generate(MockProvider(), evidence)
    assert result.root_cause_explanation.citation_ids == []
    assert "no diagnosis" in result.root_cause_explanation.claim.lower()
    assert result.evidence_gaps


# --- MockProvider: simulated failure modes --------------------------------


def test_mock_provider_return_malformed_raises_schema_validation_error():
    from pydantic import ValidationError

    evidence = _minimal_evidence()
    with pytest.raises(ValidationError):
        _generate(MockProvider(return_malformed=True), evidence)


def test_mock_provider_return_wrong_type_yields_non_basemodel():
    evidence = _minimal_evidence()
    result = _generate(MockProvider(return_wrong_type=True), evidence)
    assert not isinstance(result, CaseNarrative)
    assert isinstance(result, str)


def test_mock_provider_raise_exception_propagates():
    evidence = _minimal_evidence()

    class _BoomError(Exception):
        pass

    with pytest.raises(_BoomError):
        _generate(MockProvider(raise_exception=_BoomError("simulated provider failure")), evidence)


def test_mock_provider_fabricate_citation_flag_actually_fabricates():
    evidence = _minimal_evidence()
    result = _generate(MockProvider(fabricate_citation=True), evidence)
    valid_ids = {evidence.snapshot.reference.reference_id} | {
        e.reference.reference_id for e in evidence.timeline
    }
    fabricated = {c.evidence_id for c in result.citations} - valid_ids
    assert fabricated, "expected the fabricate_citation flag to inject an unresolvable id"


def test_mock_provider_wrong_case_id_flag_actually_lies():
    evidence = _minimal_evidence()
    result = _generate(MockProvider(wrong_case_id=True), evidence)
    assert result.case_id != evidence.case_id
