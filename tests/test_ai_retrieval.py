"""Phase 3 — `torque.ai.retrieval.find_precedent` tests.

Reuses the existing entity-creation fixtures from `tests/conftest.py`
(`make_merchant`, `make_case`) plus `torque.ai.evidence.gather_case_evidence`
/ `torque.ai.citations.resolve_citation` from Phase 1/2 for the citation
round-trip test, plus the real `torque.demo.seed.seed_demo` dataset for the
seed-data acceptance tests (§23/§25 of the Phase 3 task) — no synthetic
substitute for the real seeded corpus.

`RevenueLeakCase.recovery_type` / `.recovered_amount` are guard-protected
(INV-06/INV-53) — writable only inside `torque.models.guards.module7_writer`.
Every test here that needs a "recovered" precedent uses that context manager
to set them, exactly like `torque.demo.seed`'s own `_recover()` helper does;
this is not a boundary this test file is exempt from, it is simply not part
of `torque.ai`'s own forbidden-import list (only `src/torque/ai/*` is
checked by `tests/test_ai_boundary.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from torque.ai.citations import resolve_citation
from torque.ai.evidence import gather_case_evidence
from torque.ai.retrieval import MAX_TOP_K, find_precedent
from torque.enums import Actor, CaseEventType, CaseStatus, LegType, RecoveryType
from torque.events import append_case_event
from torque.models import Merchant, RevenueLeakCase
from torque.models.guards import module7_writer

# --- terminal-status mirror is drift-protected -----------------------------


def test_terminal_mirror_matches_state_machine_exactly():
    """`torque.ai.retrieval` cannot import `torque.state_machine` (forbidden
    — the boundary is permanent), so it maintains its own byte-for-byte
    mirror of `is_terminal`. THIS test — a test file, not `src/torque/ai/*`
    — is free to import the real thing and prove the mirror is exact across
    every (status, leg_type) combination. If a maintainer ever changes
    `state_machine.TERMINAL_STATUSES`/`is_terminal` without updating
    `retrieval.py`'s copy, this test fails loudly rather than the two
    silently drifting apart."""
    from torque.ai.retrieval import _terminal_statuses_for_leg
    from torque.state_machine import is_terminal

    for leg in LegType:
        mirrored = _terminal_statuses_for_leg(leg)
        for status in CaseStatus:
            assert (status in mirrored) == is_terminal(status, leg), (
                f"mismatch for status={status}, leg_type={leg}"
            )


# --- helpers -----------------------------------------------------------------


def _same_merchant(db, case: RevenueLeakCase) -> Merchant:
    """`make_case`'s `merchant=` kwarg wants a `Merchant` ORM object, not a
    bare id string — this fetches the one an existing case belongs to, so a
    test can create a second case "at the same merchant" cleanly."""
    merchant = db.get(Merchant, case.merchant_id)
    assert merchant is not None
    return merchant


def _resolved_case(
    db,
    make_case,
    *,
    merchant=None,
    root_cause,
    leg=LegType.PAYMENT_DEGRADATION,
    recovered_amount="500.00",
    opened_ago_days=1,
    status=CaseStatus.RECOVERED,
):
    """A terminal case with `recovered_amount` set through the sanctioned
    `module7_writer` gate (INV-06/INV-53) — never a bare attribute set."""
    case = make_case(
        merchant=merchant,
        leg=leg,
        root_cause_code=root_cause,
        status=status,
        opened_at=datetime.now(UTC) - timedelta(days=opened_ago_days),
    )
    if recovered_amount is not None:
        with module7_writer(db):
            case.recovery_type = RecoveryType.AGENT_ASSISTED
            case.recovered_amount = Decimal(recovered_amount)
            db.flush()
    return case


# --- 1. same-merchant match / 25. query quality -----------------------------


def test_same_merchant_match_returns_the_relevant_precedent(db, make_case):
    prior = _resolved_case(db, make_case, root_cause="ISSUER_SOFT_DECLINE_NSF")
    current = make_case(
        merchant=_same_merchant(db, prior),
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )

    results = find_precedent(db, current.merchant_id, current)

    assert len(results) == 1
    result = results[0]
    assert result.case_id == str(prior.case_id)
    assert result.root_cause_code == "ISSUER_SOFT_DECLINE_NSF"
    assert result.recovered is True
    assert "recovered" in result.outcome_summary.lower()


# --- 2. / 9. cross-merchant exclusion / tenant isolation --------------------


def test_cross_merchant_case_never_appears(db, make_case, make_merchant):
    other_merchant = make_merchant()
    _resolved_case(  # a perfectly matching case, but at a DIFFERENT merchant
        db, make_case, merchant=other_merchant, root_cause="ISSUER_SOFT_DECLINE_NSF"
    )
    current = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )

    results = find_precedent(db, current.merchant_id, current)

    assert results == []
    assert current.merchant_id != other_merchant.merchant_id


def test_find_precedent_rejects_merchant_case_mismatch(db, make_case, make_merchant):
    """Defensive correctness check: `merchant_id` and `case.merchant_id`
    must agree — a caller bug, not a legitimate "no precedent" outcome."""
    other_merchant = make_merchant()
    case = make_case()
    with pytest.raises(ValueError):
        find_precedent(db, other_merchant.merchant_id, case)


# --- 3. current-case exclusion ----------------------------------------------


def test_current_case_never_returned_as_its_own_precedent(db, make_case):
    current = _resolved_case(  # itself terminal / a "perfect match" for its own metadata
        db, make_case, root_cause="ISSUER_SOFT_DECLINE_NSF"
    )
    results = find_precedent(db, current.merchant_id, current)
    assert results == []
    assert all(r.case_id != str(current.case_id) for r in results)


# --- 4. / 13. in-flight / terminal-resolution restriction -------------------


def test_in_flight_case_is_never_a_precedent(db, make_case):
    make_case(  # matches metadata perfectly but is still in-flight
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )
    current = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.DIAGNOSING,
    )
    results = find_precedent(db, current.merchant_id, current)
    assert results == []


def test_partially_recovered_is_terminal_for_non_b2b_leg(db, make_case):
    prior = _resolved_case(
        db,
        make_case,
        root_cause="ISSUER_SOFT_DECLINE_NSF",
        leg=LegType.PAYMENT_DEGRADATION,
        status=CaseStatus.PARTIALLY_RECOVERED,
        recovered_amount="200.00",
    )
    current = make_case(
        merchant=_same_merchant(db, prior),
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )
    results = find_precedent(db, current.merchant_id, current)
    assert [r.case_id for r in results] == [str(prior.case_id)]


def test_partially_recovered_is_not_terminal_for_b2b_leg(db, make_case):
    prior = _resolved_case(
        db,
        make_case,
        root_cause="LIQUIDITY_DELAY_HIGH_RISK",
        leg=LegType.B2B_RECEIVABLE,
        status=CaseStatus.PARTIALLY_RECOVERED,
        recovered_amount="200.00",
    )
    current = make_case(
        merchant=_same_merchant(db, prior),
        leg=LegType.B2B_RECEIVABLE,
        root_cause_code="LIQUIDITY_DELAY_HIGH_RISK",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )
    results = find_precedent(db, current.merchant_id, current)
    assert results == []  # the B2B PARTIALLY_RECOVERED case is still open, not a precedent


# --- 5. zero matches ---------------------------------------------------------


def test_unique_root_cause_returns_empty_list(db, make_case):
    current = _resolved_case(db, make_case, root_cause="GATEWAY_TIMEOUT")
    results = find_precedent(db, current.merchant_id, current)
    assert results == []


# --- 6. top-K -----------------------------------------------------------------


def test_results_never_exceed_configured_top_k(db, make_case, make_merchant):
    merchant = make_merchant()
    for i in range(5):
        _resolved_case(
            db,
            make_case,
            merchant=merchant,
            root_cause="ISSUER_SOFT_DECLINE_NSF",
            opened_ago_days=i + 1,
        )
    current = make_case(
        merchant=merchant,
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )

    default_results = find_precedent(db, merchant.merchant_id, current)
    assert len(default_results) == 3  # DEFAULT_TOP_K

    capped_results = find_precedent(db, merchant.merchant_id, current, top_k=2)
    assert len(capped_results) == 2


def test_top_k_out_of_range_is_rejected(db, make_case):
    current = make_case()
    with pytest.raises(ValueError):
        find_precedent(db, current.merchant_id, current, top_k=0)
    with pytest.raises(ValueError):
        find_precedent(db, current.merchant_id, current, top_k=MAX_TOP_K + 1)


# --- 7. recency ---------------------------------------------------------------


def test_more_recent_precedent_ranks_first_when_lexically_tied(db, make_case):
    """Neither prior case has any CaseEvent.reasoning text (both lexical
    ranks are 0.0 / tied) — recency must be the deciding tiebreaker."""
    older = _resolved_case(
        db, make_case, root_cause="ISSUER_SOFT_DECLINE_NSF", opened_ago_days=30
    )
    newer = _resolved_case(
        db,
        make_case,
        merchant=_same_merchant(db, older),
        root_cause="ISSUER_SOFT_DECLINE_NSF",
        opened_ago_days=1,
    )
    current = make_case(
        merchant=_same_merchant(db, older),
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )

    results = find_precedent(db, older.merchant_id, current, top_k=2)

    assert [r.case_id for r in results] == [str(newer.case_id), str(older.case_id)]


# --- 8. metadata filtering ----------------------------------------------------


def test_different_leg_type_does_not_match(db, make_case):
    prior = _resolved_case(
        db, make_case, root_cause="ISSUER_SOFT_DECLINE_NSF", leg=LegType.PAYMENT_DEGRADATION
    )
    current = make_case(
        merchant=_same_merchant(db, prior),
        leg=LegType.SUBSCRIPTION_FAILURE,  # same root cause code, different leg
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
        context={
            "mandate_id": "mand_retrieval_test",
            "mandate_type": "CARD",
            "billing_cycle": "monthly",
            "subscription_id": "sub_retrieval_test",
        },
    )
    results = find_precedent(db, prior.merchant_id, current)
    assert results == []


def test_different_root_cause_does_not_match(db, make_case):
    prior = _resolved_case(db, make_case, root_cause="ISSUER_SOFT_DECLINE_NSF")
    current = make_case(
        merchant=_same_merchant(db, prior),
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="GATEWAY_TIMEOUT",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )
    results = find_precedent(db, prior.merchant_id, current)
    assert results == []


# --- 10. missing root cause ---------------------------------------------------


def test_missing_root_cause_returns_empty_list_not_broadened(db, make_case):
    _resolved_case(db, make_case, root_cause="ISSUER_SOFT_DECLINE_NSF")  # unrelated noise
    current = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code=None,
        status=CaseStatus.DETECTED,
    )
    results = find_precedent(db, current.merchant_id, current)
    assert results == []


# --- 11. missing reasoning does not crash ------------------------------------


def test_missing_reasoning_does_not_crash_retrieval(db, make_case):
    prior = _resolved_case(db, make_case, root_cause="ISSUER_SOFT_DECLINE_NSF")
    # a CaseEvent with NO reasoning at all (None) on the prior case
    append_case_event(
        db,
        case_id=prior.case_id,
        event_type=CaseEventType.STATUS_CHANGED,
        payload={"from_status": "DETECTED", "to_status": "DIAGNOSING", "trigger": "x"},
        actor=Actor.AGENT,
        reasoning=None,
    )
    db.flush()
    current = make_case(
        merchant=_same_merchant(db, prior),
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )
    results = find_precedent(db, prior.merchant_id, current)  # must not raise
    assert len(results) == 1


# --- 12. citation resolution --------------------------------------------------


def test_precedent_evidence_id_resolves_via_phase2_citation_resolver(db, make_case):
    """Every `PrecedentCase.evidence_id` must resolve through
    `torque.ai.citations.resolve_citation` against THAT precedent case's own
    `gather_case_evidence(...)` result — not the current case's."""
    prior = _resolved_case(db, make_case, root_cause="ISSUER_SOFT_DECLINE_NSF")
    append_case_event(
        db,
        case_id=prior.case_id,
        event_type=CaseEventType.PAYMENT_RECONCILED,
        payload={"recovered_amount": Decimal("500.00"), "recovery_type": "AGENT_ASSISTED"},
        actor=Actor.SYSTEM,
    )
    db.flush()

    current = make_case(
        merchant=_same_merchant(db, prior),
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )

    results = find_precedent(db, prior.merchant_id, current)
    assert len(results) == 1
    precedent = results[0]

    precedent_evidence = gather_case_evidence(
        db, merchant_id=prior.merchant_id, case_id=precedent.case_id
    )
    resolved = resolve_citation(precedent_evidence, precedent.evidence_id)
    assert resolved is not None
    assert resolved.reference.reference_id == precedent.evidence_id


def test_precedent_without_resolution_event_cites_the_case_snapshot(db, make_case):
    """An `EXHAUSTED` case has neither `PAYMENT_RECONCILED` nor
    `HUMAN_RESOLVED` — its precedent citation must fall back to the case
    snapshot's own reference, and that must still resolve."""
    prior = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="UNKNOWN_LOW_CONFIDENCE",
        status=CaseStatus.EXHAUSTED,
    )
    current = make_case(
        merchant=_same_merchant(db, prior),
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="UNKNOWN_LOW_CONFIDENCE",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )

    results = find_precedent(db, prior.merchant_id, current)
    assert len(results) == 1
    precedent = results[0]
    assert precedent.recovered is False
    assert precedent.evidence_id == f"case:{prior.case_id}"

    precedent_evidence = gather_case_evidence(
        db, merchant_id=prior.merchant_id, case_id=precedent.case_id
    )
    resolved = resolve_citation(precedent_evidence, precedent.evidence_id)
    assert resolved is not None
    assert resolved is precedent_evidence.snapshot


# --- 14. empty corpus ----------------------------------------------------------


def test_merchant_with_no_prior_cases_returns_empty_list(db, make_case):
    current = make_case(
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code="ISSUER_SOFT_DECLINE_NSF",
        status=CaseStatus.PLAYBOOK_ACTIVE,
    )
    results = find_precedent(db, current.merchant_id, current)
    assert results == []


# --- seed-data acceptance tests (§23 / §25) ----------------------------------


def test_seed_data_positive_precedent_nsf_subscription(db):
    """Positive case: `acc_demo`'s seed carries a RECOVERED
    SUBSCRIPTION_FAILURE/NSF_SOFT_DECLINE case (Aarav Mehta) AND an open,
    in-flight SUBSCRIPTION_FAILURE/NSF_SOFT_DECLINE case (Diya Kapoor / Sara
    Khan) — searching precedent for the open case must surface the recovered
    one, by exact case identity, not just a non-empty list."""
    from torque.demo.seed import DEMO_MERCHANT_ID, seed_demo

    seed_demo(db)

    open_case = db.scalars(
        select(RevenueLeakCase).where(
            RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID,
            RevenueLeakCase.leg_type == LegType.SUBSCRIPTION_FAILURE,
            RevenueLeakCase.root_cause_code == "NSF_SOFT_DECLINE",
            RevenueLeakCase.status == CaseStatus.PLAYBOOK_ACTIVE,
        )
    ).first()
    assert open_case is not None, (
        "seed data shape changed — expected an open NSF subscription case"
    )

    recovered_case = db.scalars(
        select(RevenueLeakCase).where(
            RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID,
            RevenueLeakCase.leg_type == LegType.SUBSCRIPTION_FAILURE,
            RevenueLeakCase.root_cause_code == "NSF_SOFT_DECLINE",
            RevenueLeakCase.status == CaseStatus.RECOVERED,
        )
    ).first()
    assert recovered_case is not None, (
        "seed data shape changed — expected a recovered NSF subscription case"
    )

    results = find_precedent(db, DEMO_MERCHANT_ID, open_case)

    assert len(results) >= 1
    result_ids = {r.case_id for r in results}
    assert str(recovered_case.case_id) in result_ids
    matched = next(r for r in results if r.case_id == str(recovered_case.case_id))
    assert matched.root_cause_code == "NSF_SOFT_DECLINE"
    assert matched.recovered is True


def test_seed_data_zero_precedent_gateway_timeout(db):
    """Negative case: `acc_demo`'s seed has exactly one
    PAYMENT_DEGRADATION/GATEWAY_TIMEOUT case (Priya Nair) — no duplicate
    exists, so precedent search for it must return []."""
    from torque.demo.seed import DEMO_MERCHANT_ID, seed_demo

    seed_demo(db)

    unique_case = db.scalars(
        select(RevenueLeakCase).where(
            RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID,
            RevenueLeakCase.leg_type == LegType.PAYMENT_DEGRADATION,
            RevenueLeakCase.root_cause_code == "GATEWAY_TIMEOUT",
        )
    ).first()
    assert unique_case is not None, "seed data shape changed — expected a GATEWAY_TIMEOUT case"

    # confirm it is genuinely unique within the merchant before asserting []
    duplicate = db.scalar(
        select(RevenueLeakCase.case_id)
        .where(
            RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID,
            RevenueLeakCase.leg_type == LegType.PAYMENT_DEGRADATION,
            RevenueLeakCase.root_cause_code == "GATEWAY_TIMEOUT",
            RevenueLeakCase.case_id != unique_case.case_id,
        )
        .limit(1)
    )
    assert duplicate is None, (
        "GATEWAY_TIMEOUT is no longer unique in the seed — test assumption stale"
    )

    results = find_precedent(db, DEMO_MERCHANT_ID, unique_case)
    assert results == []
