"""Phase 6 — the AI HTTP surface: `GET /ai/{merchant_id}/cases/{case_id}/explain`.

Exercises the real pipeline (`gather_case_evidence` -> `find_precedent` ->
`MockProvider` -> `explain_case`'s citation validation -> API serialization)
end to end through the ASGI app via the same `make_api_client` harness
`test_module10_api.py` uses. Only the provider-construction seam
(`torque.api.ai._get_provider`) is ever monkeypatched, and only for the one
test that needs to simulate a provider failure — every other layer runs for
real, against the same rolled-back `db` session every other API test uses.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from torque.ai.citations import resolve_citation
from torque.ai.config import AISettings, get_ai_settings
from torque.ai.evidence import gather_case_evidence
from torque.enums import CaseStatus, LegType
from torque.models import CaseEvent, RevenueLeakCase


def _enable_ai(client) -> None:
    client.app.dependency_overrides[get_ai_settings] = lambda: AISettings(enabled=True)


def _disable_ai(client) -> None:
    client.app.dependency_overrides[get_ai_settings] = lambda: AISettings(enabled=False)


def _diagnosed_case(make_case, m=None):
    return make_case(
        merchant=m,
        leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay"},
        amount_at_risk=Decimal("5000.00"),
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        root_cause_label="Issuer soft decline (NSF)",
        diagnosis_confidence=0.82,
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )


def _explain_url(merchant_id, case_id) -> str:
    return f"/ai/{merchant_id}/cases/{case_id}/explain"


# --- happy path -------------------------------------------------------


def test_explain_happy_path_returns_grounded_narrative(
    make_api_client, db, make_merchant, make_case
):
    m = make_merchant()
    c = _diagnosed_case(make_case, m)
    client = make_api_client()
    _enable_ai(client)

    r = client.get(_explain_url(m.merchant_id, c.case_id))
    assert r.status_code == 200
    body = r.json()
    assert body["case_id"] == str(c.case_id)
    assert body["provider_id"] == "mock:deterministic-v1"
    assert body["prompt_version"] == "narrative-v1"
    assert body["citations"]

    used_ids = set(body["current_state"]["citation_ids"]) | set(
        body["root_cause_explanation"]["citation_ids"]
    )
    for entry in body["timeline"] + body["actions_taken"] + body["guardrail_explanation"]:
        used_ids |= set(entry["citation_ids"])
    flat_ids = {c["evidence_id"] for c in body["citations"]}
    assert used_ids == flat_ids  # the exact-match contract Phase 4 enforces, unweakened


def test_explain_no_precedent_case(make_api_client, db, make_merchant, make_case):
    """A genuinely unique root cause -> a real, honest 'no precedent' section,
    not a fabricated comparison (Phase 3/4 semantics, unmodified)."""
    m = make_merchant()
    c = make_case(
        merchant=m, leg=LegType.PAYMENT_DEGRADATION, context={"gateway": "razorpay"},
        root_cause_code="GATEWAY_TIMEOUT", status=CaseStatus.PLAYBOOK_ACTIVE,
    )
    client = make_api_client()
    _enable_ai(client)

    body = client.get(_explain_url(m.merchant_id, c.case_id)).json()
    assert body["precedent"]["found"] is False
    assert body["precedent"]["cases"] == []


# --- tenant isolation --------------------------------------------------


def test_explain_cross_tenant_case_is_404_not_a_leak(make_api_client, db, make_merchant, make_case):
    m1 = make_merchant()
    m2 = make_merchant()
    c = _diagnosed_case(make_case, m1)
    client = make_api_client()
    _enable_ai(client)

    ok = client.get(_explain_url(m1.merchant_id, c.case_id))
    assert ok.status_code == 200

    leak = client.get(_explain_url(m2.merchant_id, c.case_id))
    assert leak.status_code == 404
    assert str(c.case_id) not in leak.text
    assert "ISSUER_SOFT_DECLINE_NSF" not in leak.text


def test_explain_unknown_merchant_is_404(make_api_client, db, make_case):
    c = make_case()
    client = make_api_client()
    _enable_ai(client)

    r = client.get(_explain_url("nobody", c.case_id))
    assert r.status_code == 404


def test_explain_unknown_case_is_404(make_api_client, db, make_merchant):
    m = make_merchant()
    client = make_api_client()
    _enable_ai(client)

    r = client.get(_explain_url(m.merchant_id, uuid.uuid4()))
    assert r.status_code == 404


# --- AI disabled ---------------------------------------------------------


def test_explain_ai_disabled_returns_503_without_touching_anything(
    make_api_client, db, make_merchant, make_case
):
    m = make_merchant()
    c = _diagnosed_case(make_case, m)
    client = make_api_client()
    _disable_ai(client)

    events_before = db.scalar(select(func.count()).select_from(CaseEvent))
    r = client.get(_explain_url(m.merchant_id, c.case_id))
    assert r.status_code == 503
    assert "case_id" not in r.json()
    events_after = db.scalar(select(func.count()).select_from(CaseEvent))
    assert events_after == events_before  # disabled -> not even a merchant lookup happened


# --- provider failure -----------------------------------------------------


def test_explain_provider_failure_maps_to_5xx_without_leaking_internals(
    make_api_client, db, make_merchant, make_case, monkeypatch
):
    from torque.ai.providers.mock_provider import MockProvider

    m = make_merchant()
    c = _diagnosed_case(make_case, m)
    client = make_api_client()
    _enable_ai(client)
    monkeypatch.setattr(
        "torque.api.ai._get_provider",
        lambda: MockProvider(raise_exception=RuntimeError("simulated provider outage")),
    )

    r = client.get(_explain_url(m.merchant_id, c.case_id))
    assert 500 <= r.status_code < 600
    body_text = r.text
    assert "simulated provider outage" not in body_text
    assert "RuntimeError" not in body_text
    assert "Traceback" not in body_text
    assert "torque.ai" not in body_text
    assert "torque/ai" not in body_text


def test_explain_fabricated_citation_maps_to_5xx(
    make_api_client, db, make_merchant, make_case, monkeypatch
):
    """A provider that fabricates a citation must never reach the caller as a
    200 — Phase 4's `_validate_citations` gate, exercised through the API,
    unweakened."""
    from torque.ai.providers.mock_provider import MockProvider

    m = make_merchant()
    c = _diagnosed_case(make_case, m)
    client = make_api_client()
    _enable_ai(client)
    monkeypatch.setattr(
        "torque.api.ai._get_provider", lambda: MockProvider(fabricate_citation=True)
    )

    r = client.get(_explain_url(m.merchant_id, c.case_id))
    assert 500 <= r.status_code < 600
    assert "fabricated-does-not-exist" not in r.text


# --- citation integrity -----------------------------------------------


def test_explain_citations_all_resolve_against_real_evidence(
    make_api_client, db, make_merchant, make_case
):
    m = make_merchant()
    c = _diagnosed_case(make_case, m)
    client = make_api_client()
    _enable_ai(client)

    body = client.get(_explain_url(m.merchant_id, c.case_id)).json()
    evidence = gather_case_evidence(db, merchant_id=m.merchant_id, case_id=c.case_id)
    for citation in body["citations"]:
        assert resolve_citation(evidence, citation["evidence_id"]) is not None, citation


# --- read-only behavior -------------------------------------------------


def test_explain_performs_no_write(make_api_client, db, make_merchant, make_case):
    m = make_merchant()
    c = _diagnosed_case(make_case, m)
    client = make_api_client()
    _enable_ai(client)

    events_before = db.scalar(select(func.count()).select_from(CaseEvent))
    case_row = db.get(RevenueLeakCase, c.case_id)
    status_before = case_row.status
    recovered_before = case_row.recovered_amount
    escalation_before = case_row.escalation_resolution

    r = client.get(_explain_url(m.merchant_id, c.case_id))
    assert r.status_code == 200

    events_after = db.scalar(select(func.count()).select_from(CaseEvent))
    assert events_after == events_before
    db.refresh(case_row)
    assert case_row.status == status_before
    assert case_row.recovered_amount == recovered_before
    assert case_row.escalation_resolution == escalation_before
    assert not db.new and not db.dirty and not db.deleted
