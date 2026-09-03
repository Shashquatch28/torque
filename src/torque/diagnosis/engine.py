"""The Diagnosis Engine orchestrator — Blueprint Module 3.

`diagnose_case` converts a Module-2 canonical case into `root_cause_code`,
`root_cause_label`, `diagnosis_confidence`, `suggested_timing_adjustment`, and —
for PAYMENT_DEGRADATION — `is_hard_decline` (D-058: Module 3 owns this verdict;
Module 2 leaves it `None`). It writes the `DIAGNOSIS_COMPLETED` `CaseEvent` and
routes the case by the `T = 0.65` confidence threshold (§3.3 / Decision E):

    DETECTED ─▶ DIAGNOSING ─▶ PLAYBOOK_ACTIVE        (confidence ≥ T)
                          └─▶ ESCALATED_TO_HUMAN     (confidence <  T, Part C item 1)

Everything for one case happens in ONE transaction (status changes + case fields
+ `CaseEvent`s), via `torque.events.atomic`. A failure at any point rolls the
whole thing back — no half-diagnosed case.

**Eligibility / idempotency.** Only a `DETECTED` case, or a `DIAGNOSING` case not
yet carrying a `root_cause_code`, is diagnosable; a superseded (§2.4-merged)
case is skipped (its signal already folded into the surviving case). Every other
state — including a case actively held at `SYSTEMIC_HOLD`, an already-diagnosed
case, a terminal case — is a no-op. The `DIAGNOSING` entry state exists because
Module 2 §2.5 re-queues systemic-hold cases straight to `DIAGNOSING` on outage
resolution; those enter here without the `DETECTED → DIAGNOSING` hop. Repeated
task execution / redelivery is therefore safe by construction.

**Boundary.** Module 3 routes the case *to* `PLAYBOOK_ACTIVE`; it does not select
or instantiate a playbook (Module 4), never touches retry budgets, outreach, or
Temporal, and does not drive systemic detection (Module 2 §2.5). Routing to
`PLAYBOOK_ACTIVE` is exactly the §3.3 contrapositive of "if confidence < T it does
**not** enter an automated playbook".

**Tenancy.** Every supporting lookup (rail budgets, invoices, the counterparty
relationship) is scoped to `case.merchant_id` via `TenantScope` — a merchant-A
case is never diagnosed with merchant-B evidence (INV-... ; Blueprint §2.1).
"""

from __future__ import annotations

import uuid
from enum import Enum, auto

from sqlalchemy import func
from sqlalchemy.orm import Session

from torque.config import get_policy
from torque.db.scoped import TenantScope
from torque.diagnosis.classifier import (
    DiagnosisResult,
    classify_b2b_receivable,
    classify_checkout_abandonment,
    classify_payment_degradation,
    classify_subscription_failure,
)
from torque.enums import (
    Actor,
    CaseEventType,
    CaseStatus,
    ClearingCycleStatus,
    LegType,
    MacTier,
    MandateType,
    PaymentMethodAttempted,
)
from torque.events.case_event_writer import append_case_event, atomic
from torque.ingestion import payloads
from torque.models import (
    B2BInvoice,
    Event,
    MerchantCounterparty,
    NACHRetryPolicy,
    RevenueLeakCase,
    UPIRetryBudget,
)
from torque.state_machine import transition_case

_DIAGNOSIS_STARTED = "diagnosis_started"
_ROUTE_CONFIDENT = "diagnosis_confident"
_ROUTE_LOW_CONFIDENCE = "diagnosis_low_confidence"


class DiagnosisOutcome(Enum):
    """The outcome of one `diagnose_case` call."""

    #: Not eligible — wrong state, superseded, already diagnosed, or missing
    #: (idempotent under redelivery).
    NOOP = auto()
    #: Diagnosed with confidence ≥ T → routed `DIAGNOSING → PLAYBOOK_ACTIVE`.
    ROUTED_TO_PLAYBOOK = auto()
    #: Diagnosed with confidence < T → routed `DIAGNOSING → ESCALATED_TO_HUMAN`.
    ESCALATED = auto()


def _diagnosis_confidence_threshold() -> float:
    """The §3.3 routing threshold `T` (Decision E — a policy value, not a
    literal; uncalibrated launch default 0.65)."""
    return get_policy().diagnosis_confidence_threshold


# --- eligibility -------------------------------------------------------------


def _is_eligible(case: RevenueLeakCase) -> bool:
    if case.superseded_by_case_id is not None:
        return False  # §2.4: narrower merged case — the survivor is diagnosed
    status = CaseStatus(case.status)
    if status is CaseStatus.DETECTED:
        return True
    if status is CaseStatus.DIAGNOSING:
        # A systemic-resumed case (Module 2 §2.5) enters DIAGNOSING directly; only
        # diagnose it if it has not already been classified.
        return case.root_cause_code is None
    return False


# --- per-leg input gathering (tenant-scoped) ---------------------------------


def _classify(session: Session, case: RevenueLeakCase) -> DiagnosisResult:
    leg = LegType(case.leg_type)
    context = case.context or {}

    if leg is LegType.PAYMENT_DEGRADATION:
        return classify_payment_degradation(
            network_directive_tier=_tier(case),
            decline_code=context.get("decline_code"),
        )
    if leg is LegType.SUBSCRIPTION_FAILURE:
        mandate_type = MandateType(context["mandate_type"])
        mandate_id = context.get("mandate_id") or ""
        return classify_subscription_failure(
            mandate_type=mandate_type,
            network_directive_tier=_tier(case),
            # SubscriptionFailureContext deliberately carries no decline_code
            # (its four fields are mandate identity only); the raw Razorpay
            # error_code lives in the source Event's payload (D-081).
            decline_code=_source_decline_code(session, case),
            clearing_cycle_status=_nach_clearing_status(
                session, case, mandate_type=mandate_type, mandate_id=mandate_id
            ),
            mandate_cancelled_at=_upi_mandate_cancelled_at(
                session, case, mandate_type=mandate_type, mandate_id=mandate_id
            ),
        )
    if leg is LegType.CHECKOUT_ABANDONMENT:
        return classify_checkout_abandonment(
            drop_stage=str(context.get("drop_stage") or ""),
            payment_method_attempted=PaymentMethodAttempted(
                context.get("payment_method_attempted")
                or PaymentMethodAttempted.NONE.value
            ),
        )
    # B2B_RECEIVABLE
    return classify_b2b_receivable(
        days_overdue=_b2b_days_overdue(session, case),
        promise_keeping_rate=_promise_keeping_rate(session, case),
        prior_invoice_count=_b2b_invoice_count(session, case),
    )


def _tier(case: RevenueLeakCase) -> MacTier | None:
    return MacTier(case.network_directive_tier) if case.network_directive_tier else None


def _source_decline_code(session: Session, case: RevenueLeakCase) -> str | None:
    """The raw Razorpay `payment.entity.error_code` from the case's source Event
    — the subscription decline code, which the typed context does not store. The
    Event is read through the tenant scope (a merchant-A case never reads a
    merchant-B Event)."""
    scope = TenantScope(session, case.merchant_id)
    event = scope.get(Event, case.source_event_id)
    if event is None:
        return None
    return payloads.payment_entity(event.raw_payload or {}).get("error_code") or None


def _upi_mandate_cancelled_at(
    session: Session, case: RevenueLeakCase, *, mandate_type: MandateType, mandate_id: str
):
    if mandate_type is not MandateType.UPI_AUTOPAY or not mandate_id:
        return None
    scope = TenantScope(session, case.merchant_id)
    budget = session.scalars(
        scope.select(UPIRetryBudget).where(UPIRetryBudget.mandate_id == mandate_id)
    ).first()
    return budget.mandate_cancelled_at if budget is not None else None


def _nach_clearing_status(
    session: Session, case: RevenueLeakCase, *, mandate_type: MandateType, mandate_id: str
) -> ClearingCycleStatus | None:
    if mandate_type is not MandateType.NACH or not mandate_id:
        return None
    scope = TenantScope(session, case.merchant_id)
    policy = session.scalars(
        scope.select(NACHRetryPolicy).where(NACHRetryPolicy.mandate_id == mandate_id)
    ).first()
    return (
        ClearingCycleStatus(policy.clearing_cycle_status) if policy is not None else None
    )


def _b2b_days_overdue(session: Session, case: RevenueLeakCase) -> int | None:
    scope = TenantScope(session, case.merchant_id)
    value = session.scalar(
        scope.select(B2BInvoice)
        .where(B2BInvoice.case_id == case.case_id)
        .with_only_columns(func.max(B2BInvoice.days_overdue))
    )
    return int(value) if value is not None else None


def _b2b_invoice_count(session: Session, case: RevenueLeakCase) -> int:
    scope = TenantScope(session, case.merchant_id)
    return int(
        session.scalar(
            scope.select(B2BInvoice)
            .where(B2BInvoice.counterparty_id == case.counterparty_id)
            .with_only_columns(func.count())
        )
        or 0
    )


def _promise_keeping_rate(session: Session, case: RevenueLeakCase) -> float | None:
    scope = TenantScope(session, case.merchant_id)
    mc = session.scalars(
        scope.select(MerchantCounterparty).where(
            MerchantCounterparty.counterparty_id == case.counterparty_id
        )
    ).first()
    return mc.promise_keeping_rate if mc is not None else None


# --- persistence -------------------------------------------------------------


def _network_directive_payload(case: RevenueLeakCase) -> dict | None:
    if not case.network_directive_tier:
        return None
    return {
        "mac_code": case.network_directive_mac_code,
        "tier": MacTier(case.network_directive_tier).value,
    }


def _apply_result(
    session: Session, case: RevenueLeakCase, result: DiagnosisResult
) -> DiagnosisOutcome:
    # 1. Enter DIAGNOSING (unless a systemic resume already did).
    if CaseStatus(case.status) is CaseStatus.DETECTED:
        transition_case(
            session,
            case,
            CaseStatus.DIAGNOSING,
            trigger=_DIAGNOSIS_STARTED,
            actor=Actor.AGENT,
        )

    # 2. Write the diagnosis fields.
    case.root_cause_code = result.root_cause_code.value
    case.root_cause_label = result.root_cause_label
    case.diagnosis_confidence = result.diagnosis_confidence
    case.suggested_timing_adjustment = result.suggested_timing_adjustment
    if (
        LegType(case.leg_type) is LegType.PAYMENT_DEGRADATION
        and result.is_hard_decline is not None
    ):
        # is_hard_decline lives in the typed PaymentDegradationContext (D-058).
        # Reassign a fresh dict so SQLAlchemy tracks the JSONB change.
        ctx = dict(case.context or {})
        ctx["is_hard_decline"] = result.is_hard_decline
        case.context = ctx

    # 3. The DIAGNOSIS_COMPLETED audit event (reasoning → UI "Agent Reasoning").
    append_case_event(
        session,
        case_id=case.case_id,
        event_type=CaseEventType.DIAGNOSIS_COMPLETED,
        payload={
            "root_cause_code": result.root_cause_code.value,
            "diagnosis_confidence": result.diagnosis_confidence,
            "network_directive": _network_directive_payload(case),
        },
        actor=Actor.AGENT,
        reasoning=result.reasoning,
        counterparty_id=case.counterparty_id,
    )

    # 4. Route on the confidence threshold (§3.3).
    threshold = _diagnosis_confidence_threshold()
    if result.diagnosis_confidence >= threshold:
        transition_case(
            session,
            case,
            CaseStatus.PLAYBOOK_ACTIVE,
            trigger=_ROUTE_CONFIDENT,
            actor=Actor.AGENT,
            reasoning=result.reasoning,
        )
        session.flush()
        return DiagnosisOutcome.ROUTED_TO_PLAYBOOK
    transition_case(
        session,
        case,
        CaseStatus.ESCALATED_TO_HUMAN,
        trigger=_ROUTE_LOW_CONFIDENCE,
        actor=Actor.AGENT,
        reasoning=result.reasoning,
    )
    session.flush()
    return DiagnosisOutcome.ESCALATED


# --- entry point -------------------------------------------------------------


def diagnose_case(session: Session, *, case_id: uuid.UUID) -> DiagnosisOutcome:
    """Diagnose one case by id. Idempotent; the caller owns the transaction
    (the Celery task's `session_scope`). All writes are wrapped in one atomic
    unit — a failure rolls back the whole diagnosis."""
    case = session.get(RevenueLeakCase, case_id)
    if case is None or not _is_eligible(case):
        return DiagnosisOutcome.NOOP

    with atomic(session):
        result = _classify(session, case)
        return _apply_result(session, case, result)
