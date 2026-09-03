"""Module 3 — tenant isolation (Blueprint §2.1).

A merchant-A case must never be diagnosed using merchant-B evidence. Every
supporting lookup the engine makes — rail budgets (UPI/NACH), the counterparty
relationship, invoices, and the source Event — is scoped to the case's merchant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from torque.diagnosis import diagnose_case
from torque.diagnosis.root_causes import RootCauseCode
from torque.enums import ClearingCycleStatus, LegType, MandateType
from torque.models import (
    B2BInvoice,
    MerchantCounterparty,
    NACHRetryPolicy,
    UPIRetryBudget,
)

RC = RootCauseCode


def _sub_case(make_case, m, cp, *, mandate_type, mandate_id):
    return make_case(
        merchant=m,
        counterparty=cp,
        leg=LegType.SUBSCRIPTION_FAILURE,
        context={
            "mandate_id": mandate_id,
            "mandate_type": mandate_type.value,
            "billing_cycle": "2",
            "subscription_id": "sub_x",
        },
    )


def test_upi_cancellation_from_other_merchant_is_not_seen(
    db, make_merchant, make_counterparty, make_case
):
    shared_mandate = "mandate_shared_upi"
    a, b = make_merchant(), make_merchant()
    cp = make_counterparty()

    # Merchant B has a CANCELLED UPI mandate under the same external mandate id.
    db.add(
        UPIRetryBudget(
            merchant_id=b.merchant_id,
            mandate_id=shared_mandate,
            attempts_used=3,
            mandate_cancelled_at=datetime.now(UTC),
        )
    )
    db.flush()

    # Merchant A's case, same mandate id, but A has NO cancellation on record.
    case = _sub_case(
        make_case, a, cp, mandate_type=MandateType.UPI_AUTOPAY, mandate_id=shared_mandate
    )
    from torque.models import Event

    ev = db.get(Event, case.source_event_id)
    ev.raw_payload = {"payload": {"payment": {"entity": {"error_code": "insufficient_funds"}}}}
    db.flush()

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    # Must NOT be UPI_AUTOPAY_CAP_EXHAUSTED (that would be B's evidence leaking).
    assert case.root_cause_code == RC.NSF_SOFT_DECLINE.value


def test_nach_clearing_from_other_merchant_is_not_seen(
    db, make_merchant, make_counterparty, make_case
):
    shared_mandate = "mandate_shared_nach"
    a, b = make_merchant(), make_merchant()
    cp = make_counterparty()

    db.add(
        NACHRetryPolicy(
            merchant_id=b.merchant_id,
            mandate_id=shared_mandate,
            clearing_cycle_status=ClearingCycleStatus.PENDING_CLEARING,
            dishonour_count_this_fy=0,
        )
    )
    db.flush()

    case = _sub_case(
        make_case, a, cp, mandate_type=MandateType.NACH, mandate_id=shared_mandate
    )
    from torque.models import Event

    ev = db.get(Event, case.source_event_id)
    ev.raw_payload = {"payload": {"payment": {"entity": {"error_code": "insufficient_funds"}}}}
    db.flush()

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    # Must NOT be NACH_CLEARING_PENDING (B's clearing status must not leak).
    assert case.root_cause_code == RC.NSF_SOFT_DECLINE.value


def test_b2b_promise_keeping_rate_is_merchant_scoped(
    db, make_merchant, make_counterparty, make_case
):
    a, b = make_merchant(), make_merchant()
    cp = make_counterparty()

    # Merchant B has a rich relationship (established, would be 0.8 confidence).
    db.add(
        MerchantCounterparty(
            merchant_id=b.merchant_id,
            counterparty_id=cp.counterparty_id,
            promise_keeping_rate=0.9,
        )
    )
    db.flush()

    # Merchant A's B2B case for the same counterparty — A has no relationship
    # row and no invoices → cold-start (0.4), NOT B's established 0.8.
    case = make_case(merchant=a, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={})
    db.add(
        B2BInvoice(
            merchant_id=a.merchant_id,
            counterparty_id=cp.counterparty_id,
            case_id=case.case_id,
            due_date=(datetime.now(UTC) - timedelta(days=15)).date(),
            days_overdue=15,
            original_amount=1000,
            outstanding_amount=1000,
        )
    )
    db.flush()

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    assert case.diagnosis_confidence == 0.4  # cold-start, not B's 0.8


def test_b2b_invoice_count_is_merchant_scoped(
    db, make_merchant, make_counterparty, make_case
):
    """Merchant B's 3 invoices for the counterparty must not make merchant A's
    case look established."""
    a, b = make_merchant(), make_merchant()
    cp = make_counterparty()
    db.add(
        MerchantCounterparty(
            merchant_id=a.merchant_id,
            counterparty_id=cp.counterparty_id,
            promise_keeping_rate=0.9,
        )
    )
    for _ in range(3):
        db.add(
            B2BInvoice(
                merchant_id=b.merchant_id,
                counterparty_id=cp.counterparty_id,
                case_id=None,
                due_date=(datetime.now(UTC) - timedelta(days=15)).date(),
                days_overdue=15,
                original_amount=1000,
                outstanding_amount=1000,
            )
        )
    db.flush()

    case = make_case(merchant=a, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={})
    db.add(
        B2BInvoice(
            merchant_id=a.merchant_id,
            counterparty_id=cp.counterparty_id,
            case_id=case.case_id,
            due_date=(datetime.now(UTC) - timedelta(days=15)).date(),
            days_overdue=15,
            original_amount=1000,
            outstanding_amount=1000,
        )
    )
    db.flush()

    diagnose_case(db, case_id=case.case_id)
    db.refresh(case)
    # A has only 1 invoice of its own → cold-start confidence, not established.
    assert case.diagnosis_confidence == 0.4
