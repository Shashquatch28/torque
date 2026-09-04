"""Real-domain-data builders for Phase 7 (Shadow ML) tests.

Mirrors the same pattern `tests/ai_eval_cases.py` established for Phase 5:
plain builder functions, called directly from test bodies with `db` already
in scope, that drive real ORM rows through the real event-payload machinery
— never a parallel fake domain model. The one deliberate departure from
`append_case_event` (used everywhere else in this codebase) is that these
helpers accept an explicit `timestamp` for the `CaseEvent` they write,
because Postgres's `now()` (`CaseEvent.timestamp`'s server default) resolves
to the surrounding transaction's start time — a single fixed instant for
every event a given test writes — which makes it impossible to construct
"event A before cutoff, event B after cutoff" fixtures using the server
default inside one test transaction. Fixture data only; tests still exercise
the same locked, schema-validated `torque.events.payloads.validate_payload`
every real write path uses.
"""

from __future__ import annotations

from datetime import timedelta

from torque.enums import Actor, CaseEventType, CaseStatus, LegType, MacTier
from torque.events.payloads import validate_payload
from torque.models import B2BInvoice, CaseEvent, MerchantCounterparty


def write_event(db, case, *, event_type, payload, timestamp, actor=Actor.SYSTEM):
    """Stage a schema-validated `CaseEvent` with an explicit `timestamp`,
    bypassing `append_case_event`'s server-side `now()` default (see module
    docstring)."""
    validated = validate_payload(event_type, payload)
    row = CaseEvent(
        case_id=case.case_id,
        event_type=CaseEventType(event_type),
        payload=validated,
        actor=Actor(actor),
        timestamp=timestamp,
    )
    db.add(row)
    db.flush()
    return row


def diagnose(
    db,
    case,
    *,
    root_cause_code="NSF_SOFT_DECLINE",
    diagnosis_confidence=0.8,
    at=None,
):
    """Write the case-row diagnosis fields + a matching `DIAGNOSIS_COMPLETED`
    event, exactly the two facts Module 3's real `diagnose_case` writes
    atomically (INV-36) — reproduced by hand since `torque.diagnosis` is a
    forbidden import for `src/torque/ai/*` but tests may use it freely; kept
    as a hand-written mirror here purely so callers control the timestamp.
    """
    at = at if at is not None else case.opened_at + timedelta(hours=1)
    case.root_cause_code = root_cause_code
    case.diagnosis_confidence = diagnosis_confidence
    db.flush()
    write_event(
        db,
        case,
        event_type=CaseEventType.DIAGNOSIS_COMPLETED,
        payload={
            "root_cause_code": root_cause_code,
            "diagnosis_confidence": diagnosis_confidence,
            "network_directive": None,
        },
        timestamp=at,
    )
    return at


def receive_network_directive(
    db, case, *, tier: MacTier, at, mac_code="21", attempt_number=1
):
    return write_event(
        db,
        case,
        event_type=CaseEventType.NETWORK_DIRECTIVE_RECEIVED,
        payload={
            "mac_code": mac_code,
            "tier": tier.value,
            "attempt_number": attempt_number,
            "received_at": at.isoformat(),
        },
        timestamp=at,
    )


def set_counterparty_relationship(db, case, *, promise_keeping_rate=None, risk_score=None):
    """Create (or update) the `MerchantCounterparty` row for `case`'s own
    `(merchant_id, counterparty_id)` pair."""
    existing = (
        db.query(MerchantCounterparty)
        .filter_by(merchant_id=case.merchant_id, counterparty_id=case.counterparty_id)
        .one_or_none()
    )
    if existing is None:
        existing = MerchantCounterparty(
            merchant_id=case.merchant_id, counterparty_id=case.counterparty_id
        )
        db.add(existing)
    existing.promise_keeping_rate = promise_keeping_rate
    existing.risk_score = risk_score
    db.flush()
    return existing


def add_b2b_invoice(
    db, case, *, original_amount, outstanding_amount, due_date, days_overdue=0
):
    invoice = B2BInvoice(
        case_id=case.case_id,
        merchant_id=case.merchant_id,
        counterparty_id=case.counterparty_id,
        due_date=due_date,
        days_overdue=days_overdue,
        original_amount=original_amount,
        outstanding_amount=outstanding_amount,
    )
    db.add(invoice)
    db.flush()
    return invoice


def make_terminal_diagnosed_case(
    db,
    make_case,
    *,
    status: CaseStatus,
    leg: LegType = LegType.PAYMENT_DEGRADATION,
    root_cause_code="NSF_SOFT_DECLINE",
    diagnosis_confidence=0.8,
    opened_days_ago: float = 5.0,
    diagnosed_hours_after_open: float = 1.0,
    amount_at_risk=1000,
    context=None,
    merchant=None,
    counterparty=None,
):
    """The one-stop builder most Phase 7 tests need: a case already at a
    terminal `status`, already diagnosed at a controlled cutoff a controlled
    number of days after it opened — real ORM rows, real event-payload
    validation, deterministic timestamps."""
    from datetime import UTC, datetime

    opened_at = datetime.now(UTC) - timedelta(days=opened_days_ago)
    kwargs = {"status": status, "opened_at": opened_at, "amount_at_risk": amount_at_risk}
    if context is not None:
        kwargs["context"] = context
    case = make_case(leg=leg, merchant=merchant, counterparty=counterparty, **kwargs)
    diagnose(
        db,
        case,
        root_cause_code=root_cause_code,
        diagnosis_confidence=diagnosis_confidence,
        at=opened_at + timedelta(hours=diagnosed_hours_after_open),
    )
    return case
