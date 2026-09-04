"""Phase 2 — `torque.ai.citations` tests.

Reuses the existing entity-creation fixtures from `tests/conftest.py`
(`make_merchant`, `make_case`, `make_action`) plus `torque.ai.evidence.
gather_case_evidence` from Phase 1 — no evidence layer is mocked away; every
test here exercises the real, database-backed evidence-gathering path before
resolving citations against its real output.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from torque.ai.citations import all_evidence_items, citation_for, resolve_citation
from torque.ai.evidence import gather_case_evidence
from torque.ai.schemas import Citation
from torque.enums import Actor, CaseEventType
from torque.events import append_case_event

# --- Citation schema --------------------------------------------------------


def test_citation_is_a_minimal_frozen_dto():
    citation = Citation(evidence_id="case:1234")
    assert citation.evidence_id == "case:1234"
    assert citation.model_dump() == {"evidence_id": "case:1234"}


def test_citation_rejects_extra_fields():
    """`extra="forbid"` — the same discipline every other AI DTO uses (§4A:
    "keep the contract intentionally small and stable")."""
    with pytest.raises(ValidationError):
        Citation(evidence_id="case:1234", excerpt="not part of the contract")


def test_citation_is_frozen():
    citation = Citation(evidence_id="case:1234")
    with pytest.raises(ValidationError):
        citation.evidence_id = "case:5678"


# --- Stable evidence IDs -----------------------------------------------------


def test_every_evidence_item_has_a_unique_id_within_the_set(db, make_action):
    """Test 1 (§7) — uniqueness within an EvidenceSet."""
    action = make_action()
    append_case_event(
        db,
        case_id=action.primary_case_id,
        event_type=CaseEventType.STATUS_CHANGED,
        payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "x"},
        actor=Actor.AGENT,
    )
    db.flush()

    evidence = gather_case_evidence(
        db, merchant_id=action.merchant_id, case_id=action.primary_case_id
    )
    items = all_evidence_items(evidence)
    ids = [item.reference.reference_id for item in items]

    assert len(items) >= 3  # snapshot + at least one event + one action
    assert len(ids) == len(set(ids)), f"duplicate evidence ids found: {ids}"


def test_evidence_ids_are_stable_across_repeated_gathering(db, make_action):
    """Test 2 (§7) — deterministic repeatability. Calling
    `gather_case_evidence` twice for the same, unchanged case must produce
    byte-identical evidence ids."""
    action = make_action()
    case_id = action.primary_case_id

    first = gather_case_evidence(db, merchant_id=action.merchant_id, case_id=case_id)
    second = gather_case_evidence(db, merchant_id=action.merchant_id, case_id=case_id)

    first_ids = [item.reference.reference_id for item in all_evidence_items(first)]
    second_ids = [item.reference.reference_id for item in all_evidence_items(second)]
    assert first_ids == second_ids


def test_snapshot_id_is_derived_from_case_id_not_position_or_time(db, make_case):
    """§4B — the id must be deterministically derived from an authoritative
    identifier, never from array position or a timestamp."""
    case = make_case()
    evidence = gather_case_evidence(db, merchant_id=case.merchant_id, case_id=case.case_id)
    assert evidence.snapshot.reference.reference_id == f"case:{case.case_id}"


def test_case_event_id_is_derived_from_event_seq_id(db, make_case):
    case = make_case()
    row = append_case_event(
        db,
        case_id=case.case_id,
        event_type=CaseEventType.STATUS_CHANGED,
        payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "x"},
        actor=Actor.AGENT,
    )
    db.flush()
    evidence = gather_case_evidence(db, merchant_id=case.merchant_id, case_id=case.case_id)
    assert evidence.timeline[0].reference.reference_id == f"case_event:{row.event_seq_id}"


# --- Resolution --------------------------------------------------------------


def test_resolve_citation_finds_every_item_in_the_set(db, make_action):
    """Test 3 (§7) — resolvability: every id in the set resolves back to its
    own item, for every evidence type Phase 1 currently produces."""
    action = make_action()
    append_case_event(
        db,
        case_id=action.primary_case_id,
        event_type=CaseEventType.STATUS_CHANGED,
        payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "x"},
        actor=Actor.AGENT,
    )
    db.flush()

    evidence = gather_case_evidence(
        db, merchant_id=action.merchant_id, case_id=action.primary_case_id
    )
    for item in all_evidence_items(evidence):
        resolved = resolve_citation(evidence, item.reference.reference_id)
        assert resolved == item


def test_citation_for_round_trips_through_resolve_citation(db, make_case):
    case = make_case()
    evidence = gather_case_evidence(db, merchant_id=case.merchant_id, case_id=case.case_id)
    citation = citation_for(evidence.snapshot)
    assert resolve_citation(evidence, citation.evidence_id) == evidence.snapshot


def test_fabricated_id_resolves_to_none_not_an_exception(db, make_case):
    """Test 4 (§7) — a fabricated id must return None, never raise."""
    case = make_case()
    evidence = gather_case_evidence(db, merchant_id=case.merchant_id, case_id=case.case_id)
    assert resolve_citation(evidence, "fake:not-a-real-evidence-id") is None


def test_wrong_case_evidence_id_does_not_resolve(db, make_case):
    """Test 5 (§7) — an evidence id that is well-formed and even carries a
    real, existing case_id, but belongs to a DIFFERENT case's evidence set,
    must not resolve."""
    case_a = make_case()
    case_b = make_case()

    evidence_a = gather_case_evidence(
        db, merchant_id=case_a.merchant_id, case_id=case_a.case_id
    )
    evidence_b = gather_case_evidence(
        db, merchant_id=case_b.merchant_id, case_id=case_b.case_id
    )
    id_from_a = evidence_a.snapshot.reference.reference_id
    assert id_from_a != evidence_b.snapshot.reference.reference_id

    # a's own snapshot id must not resolve against b's evidence set
    assert resolve_citation(evidence_b, id_from_a) is None
    # sanity: it does resolve against its own set
    assert resolve_citation(evidence_a, id_from_a) is not None


def test_malformed_ids_fail_safely(db, make_case):
    """Test 6 (§7) — malformed/empty ids resolve to None, no exception."""
    case = make_case()
    evidence = gather_case_evidence(db, merchant_id=case.merchant_id, case_id=case.case_id)

    assert resolve_citation(evidence, "") is None
    assert resolve_citation(evidence, "garbage") is None
    assert resolve_citation(evidence, ":::") is None
    assert resolve_citation(evidence, "case_event:") is None
    assert resolve_citation(evidence, "case_event:999999999") is None


# --- Tenant isolation --------------------------------------------------------


def test_cross_tenant_evidence_id_does_not_resolve(db, make_merchant, make_case):
    """§8 — an evidence id belonging to merchant A's case must never resolve
    against merchant B's evidence set, even for a different case at merchant
    B, even though nothing here queries the database at all."""
    merchant_b = make_merchant()
    case_a = make_case()  # its own fresh merchant, per make_case's default
    case_b = make_case(merchant=merchant_b)

    evidence_a = gather_case_evidence(
        db, merchant_id=case_a.merchant_id, case_id=case_a.case_id
    )
    evidence_b = gather_case_evidence(
        db, merchant_id=case_b.merchant_id, case_id=case_b.case_id
    )
    assert case_a.merchant_id != case_b.merchant_id

    id_from_a = evidence_a.snapshot.reference.reference_id
    assert resolve_citation(evidence_b, id_from_a) is None


# --- Empty / multi-type evidence sets ---------------------------------------


def test_empty_evidence_set_still_resolves_its_own_snapshot(db, make_case):
    """A fresh case has no events/actions/promises/relationship yet — the
    only citable item is the snapshot itself, and it must still resolve."""
    case = make_case()
    evidence = gather_case_evidence(db, merchant_id=case.merchant_id, case_id=case.case_id)

    items = all_evidence_items(evidence)
    assert len(items) == 1
    assert items[0] is evidence.snapshot

    resolved = resolve_citation(evidence, evidence.snapshot.reference.reference_id)
    assert resolved == evidence.snapshot


def test_multiple_evidence_types_all_resolve_independently(db, make_action):
    """A case carrying a CaseEvent, an Action, and (via a directly-added row)
    a counterparty relationship — every type must resolve to itself and only
    itself."""
    from torque.models import MerchantCounterparty, RevenueLeakCase

    action = make_action()
    case_id = action.primary_case_id
    append_case_event(
        db,
        case_id=case_id,
        event_type=CaseEventType.STATUS_CHANGED,
        payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "x"},
        actor=Actor.AGENT,
    )
    case = db.get(RevenueLeakCase, case_id)
    db.add(
        MerchantCounterparty(
            merchant_id=action.merchant_id,
            counterparty_id=case.counterparty_id,
            promise_keeping_rate=0.6,
        )
    )
    db.flush()

    evidence = gather_case_evidence(db, merchant_id=action.merchant_id, case_id=case_id)
    items = all_evidence_items(evidence)
    source_types = {item.reference.source_type for item in items}
    assert source_types == {"case", "case_event", "action", "counterparty_relationship"}

    for item in items:
        resolved = resolve_citation(evidence, item.reference.reference_id)
        assert resolved == item
        # and every OTHER item's id must not accidentally match this one
        other_ids = [
            other.reference.reference_id for other in items if other is not item
        ]
        assert item.reference.reference_id not in other_ids
