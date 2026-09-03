"""Payment reconciliation & attribution — Blueprint Module 7.

`reconcile_event` is the single entry point. It consumes an already-verified,
already-persisted success `Event` from Module 2's pipeline (§7.3 — Module 7 runs
no webhook path of its own), matches it to open `RevenueLeakCase`s, decides who
gets credit for the recovery, and closes the case(s) correctly.

Matching (§7.1), first rule that applies wins:

1. **Direct via `PaymentLink`** — a `payment_link.paid` / `.partially_paid` for a
   link Torque holds a row for → attribute fully to that link's `case_id`,
   `recovery_type = AGENT_ASSISTED`.
2. **Indirect** — a `payment.captured` / `subscription.charged` with exactly one
   open case matching `(merchant_id, counterparty_id, amount)` → attribute to it;
   `AGENT_ASSISTED` if Torque executed an `Action` for the case within the
   attribution window (`PolicyConfig.attribution_window_hours`, 24h), else
   `SELF_RECOVERED`.
3. **Multiple open cases match** — if they share one merged outreach `Action`
   (the Outreach Coordinator's §4.4 merge), re-split that `Action`'s
   `ActionCase.credit_weight` proportional to each case's `amount_at_risk` and
   recover them all (`AGENT_ASSISTED`); otherwise attribute the payment to the
   most-recently-actioned case as `AMBIGUOUS` and leave the rest open.
4. **No open case matches** — if a pre-diagnosis (`DETECTED` / `DIAGNOSING`) case
   matches, the customer self-paid before Torque could act → close it `CANCELLED`
   / `SELF_RECOVERED`; otherwise there is nothing to reconcile.

Closure (§7.2): full amount → `RECOVERED`, `recovered_amount = amount_at_risk`,
`closed_at = now`. B2B partial → `PARTIALLY_RECOVERED`, case stays open, the
matching `B2BInvoice.outstanding_amount` is decremented and `amount_at_risk`
follows (INV-33).

Guarantees: the whole reconciliation of one `Event` is one transaction (the
Celery task's `session_scope`); `recovery_type` / `recovered_amount` are written
only inside `guards.module7_writer` (INV-06); a `PAYMENT_RECONCILED` `CaseEvent`
is written atomically with the close; the matched case rows are `SELECT … FOR
UPDATE` so two workers cannot double-close; re-running on a `processed` `Event`
is a `NOOP` (idempotent under redelivery).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum, auto

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torque.config import get_policy
from torque.coordination import human_queue
from torque.db.scoped import TenantScope
from torque.enums import Actor, CaseEventType, CaseStatus, LegType, PaymentLinkStatus, RecoveryType
from torque.events.case_event_writer import append_case_event
from torque.ingestion import payloads as ingest_payloads
from torque.ingestion.identity import find_counterparty
from torque.models import (
    Action,
    ActionCase,
    B2BInvoice,
    Event,
    PaymentLink,
    RevenueLeakCase,
)
from torque.models.guards import module7_writer
from torque.reconciliation import payloads as pl_payloads
from torque.state_machine import transition_case

# Event types Module 7 consumes (§7.1). `payment.captured` / `subscription.charged`
# are also read by Module 2's self-recovery buffers off the persisted rows — that
# is unaffected; reconciliation operates on its own Event and is correct whenever
# it runs (no case yet → NO_MATCH; case present → recover / cancel).
RECONCILE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "payment.captured",
        "subscription.charged",
        "payment_link.paid",
        "payment_link.partially_paid",
        "payment_link.expired",
        "payment_link.cancelled",
    }
)
_LINK_TYPES = frozenset(
    {
        "payment_link.paid",
        "payment_link.partially_paid",
        "payment_link.expired",
        "payment_link.cancelled",
    }
)
_LINK_RECONCILING = frozenset({"payment_link.paid", "payment_link.partially_paid"})

# Cases reconciliation will close on a payment match.
_ACTIONABLE: frozenset[CaseStatus] = frozenset(
    {CaseStatus.PLAYBOOK_ACTIVE, CaseStatus.ESCALATED_TO_HUMAN}
)
# Pre-diagnosis states the §7.1.4 self-paid → CANCELLED path targets.
_PRE_DIAGNOSIS: frozenset[CaseStatus] = frozenset(
    {CaseStatus.DETECTED, CaseStatus.DIAGNOSING}
)

_ZERO = Decimal("0.00")
_ONE = Decimal("1.00000")
_W_QUANT = Decimal("0.00001")

_STATUS_MAP: dict[str, PaymentLinkStatus] = {
    "issued": PaymentLinkStatus.ISSUED,
    "partially_paid": PaymentLinkStatus.PARTIALLY_PAID,
    "paid": PaymentLinkStatus.PAID,
    "expired": PaymentLinkStatus.EXPIRED,
    "cancelled": PaymentLinkStatus.CANCELLED,
}


class ReconcileOutcome(Enum):
    #: Event missing / already processed / not a reconciliation type.
    NOOP = auto()
    #: A single case was fully recovered (RECOVERED).
    RECOVERED = auto()
    #: A B2B case was partially recovered (case stays open, PARTIALLY_RECOVERED).
    PARTIALLY_RECOVERED = auto()
    #: A merged-outreach set of cases was recovered together (§7.1.3).
    MULTI_RECOVERED = auto()
    #: Multiple non-merged cases matched; the payment was attributed to one as
    #: AMBIGUOUS, the rest left open.
    AMBIGUOUS_RECOVERED = auto()
    #: A pre-diagnosis case was closed CANCELLED / SELF_RECOVERED (§7.1.4).
    SELF_PAID_CANCELLED = auto()
    #: A payment_link.expired / .cancelled updated the row; no recovery.
    LINK_UPDATED = auto()
    #: No case (of any status) matched — nothing to reconcile.
    NO_MATCH = auto()


def reconcile_event(
    session: Session, *, event_id: uuid.UUID, now: datetime | None = None
) -> ReconcileOutcome:
    """Reconcile one persisted success `Event`. Idempotent; the caller owns the
    transaction. All writes are one atomic unit."""
    now = now or datetime.now(UTC)
    event = session.get(Event, event_id)
    if event is None or event.processed or event.type not in RECONCILE_EVENT_TYPES:
        return ReconcileOutcome.NOOP

    payload = event.raw_payload or {}
    if event.type in _LINK_TYPES:
        outcome = _reconcile_payment_link(session, event, payload, now=now)
    else:
        outcome = _reconcile_direct_payment(session, event, payload, now=now)

    event.processed = True
    session.flush()
    return outcome


# --- payment_link.* -------------------------------------------------------


def _reconcile_payment_link(
    session: Session, event: Event, payload: dict, *, now: datetime
) -> ReconcileOutcome:
    merchant_id = event.merchant_id
    scope = TenantScope(session, merchant_id)
    link_id = pl_payloads.payment_link_id(payload)
    if not link_id:
        return ReconcileOutcome.NOOP

    link = scope.get(PaymentLink, link_id)
    status_str = pl_payloads.payment_link_status(payload) or event.type.split(".", 1)[1]
    new_status = _STATUS_MAP.get(status_str)

    if link is None:
        # A link Torque generated will carry a case ref in its notes — create the
        # row so the direct-match path (and Module 9) can see it. A fully external
        # link with no Torque case is not recorded; a paid/partially_paid one then
        # falls through to indirect matching by (merchant, counterparty, amount).
        case_ref = pl_payloads.payment_link_case_ref(payload)
        case = _case_by_ref(scope, case_ref)
        if case is None:
            if event.type in _LINK_RECONCILING:
                return _reconcile_direct_payment(
                    session, event, payload, now=now, from_link=True
                )
            return ReconcileOutcome.NOOP
        # Insert with the coherent default; the status / amount_paid / paid_at
        # update below sets the paid state atomically (the row CHECK is
        # `(status = 'paid') = (paid_at IS NOT NULL)`).
        link = PaymentLink(
            link_id=link_id,
            case_id=case.case_id,
            action_id=None,
            status=PaymentLinkStatus.ISSUED,
            amount_paid=_ZERO,
        )
        scope.add(link)
        session.flush()

    paid_rupees = pl_payloads.payment_link_amount_paid_rupees(payload)
    if new_status is not None:
        link.status = new_status
    link.amount_paid = paid_rupees
    link.paid_at = now if new_status is PaymentLinkStatus.PAID else None
    session.flush()

    if event.type not in _LINK_RECONCILING:
        return ReconcileOutcome.LINK_UPDATED

    # §7.1.1 — direct match on the link's case.
    case = session.scalars(
        scope.select(RevenueLeakCase)
        .where(RevenueLeakCase.case_id == link.case_id)
        .with_for_update()
    ).first()
    if case is None or CaseStatus(case.status) not in _ACTIONABLE:
        # link points at a pre-diagnosis or already-closed case — nothing to do
        # beyond the row update we just made.
        return ReconcileOutcome.LINK_UPDATED
    applied = _apply_recovery(
        session, case, paid_rupees, event, RecoveryType.AGENT_ASSISTED, now=now
    )
    return applied


def _case_by_ref(scope: TenantScope, ref: str | None) -> RevenueLeakCase | None:
    if not ref:
        return None
    try:
        cid = uuid.UUID(str(ref))
    except (ValueError, AttributeError):
        return None
    return scope.get(RevenueLeakCase, cid)


# --- payment.captured / subscription.charged ----------------------------


def _reconcile_direct_payment(
    session: Session,
    event: Event,
    payload: dict,
    *,
    now: datetime,
    from_link: bool = False,
) -> ReconcileOutcome:
    merchant_id = event.merchant_id
    scope = TenantScope(session, merchant_id)

    amount = ingest_payloads.amount_rupees(payload)
    if from_link:
        phone = pl_payloads.payment_link_contact_phone(payload)
        email = pl_payloads.payment_link_contact_email(payload)
        amount = pl_payloads.payment_link_amount_paid_rupees(payload) or amount
    else:
        phone = ingest_payloads.contact_phone(payload)
        email = ingest_payloads.contact_email(payload)

    cp = find_counterparty(session, phone=phone, email=email)
    if cp is None or amount <= _ZERO:
        return ReconcileOutcome.NO_MATCH

    sub_id = ingest_payloads.subscription_id(payload) or None
    matched = _match_open_cases(
        session, scope, cp.counterparty_id, amount, sub_id=sub_id
    )

    if len(matched) == 1:
        case = matched[0]
        rtype = (
            RecoveryType.AGENT_ASSISTED
            if _torque_acted_within_window(session, case, now=now)
            else RecoveryType.SELF_RECOVERED
        )
        return _apply_recovery(session, case, amount, event, rtype, now=now)

    if len(matched) > 1:
        merged_action = _find_merged_action(session, [c.case_id for c in matched])
        if merged_action is not None:
            return _reconcile_merged(session, matched, merged_action, event, now=now)
        chosen = _most_recently_actioned(session, matched)
        _apply_recovery(session, chosen, amount, event, RecoveryType.AMBIGUOUS, now=now)
        return ReconcileOutcome.AMBIGUOUS_RECOVERED

    # No individual amount match. §7.1.3 — a merged-outreach set whose *combined*
    # `amount_at_risk` the lump payment settles.
    merged = _match_merged_set(session, scope, cp.counterparty_id, amount)
    if merged is not None:
        action, cases = merged
        return _reconcile_merged(session, cases, action, event, now=now)

    # §7.1.4 — nothing open matched; a pre-diagnosis case → customer self-paid.
    return _try_self_paid_cancel(session, scope, cp.counterparty_id, amount, event, now=now)


def _reconcile_merged(
    session: Session,
    cases: list[RevenueLeakCase],
    merged_action: Action,
    event: Event,
    *,
    now: datetime,
) -> ReconcileOutcome:
    """§7.1.3 — the Outreach Coordinator merged these cases into one `Action`.
    Re-split that `Action`'s `ActionCase.credit_weight` proportional to each
    case's `amount_at_risk`, then recover every case (`AGENT_ASSISTED` — a merged
    Torque outreach ran)."""
    _resplit_credit_weight(session, merged_action, cases)
    for case in cases:
        _apply_recovery(
            session, case, case.amount_at_risk, event,
            RecoveryType.AGENT_ASSISTED, now=now,
        )
    return ReconcileOutcome.MULTI_RECOVERED


def _match_open_cases(
    session: Session,
    scope: TenantScope,
    counterparty_id: uuid.UUID,
    amount: Decimal,
    *,
    sub_id: str | None,
) -> list[RevenueLeakCase]:
    """Open cases for this counterparty whose amount the payment can settle.
    Non-B2B: exact `amount_at_risk == amount`. B2B: also a partial
    (`amount < amount_at_risk`) and also `PARTIALLY_RECOVERED` cases (still
    dunning the remainder). Rows are `FOR UPDATE` — two payments cannot race to
    close the same case."""
    rows = session.scalars(
        scope.select(RevenueLeakCase)
        .where(RevenueLeakCase.counterparty_id == counterparty_id)
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
        .where(
            RevenueLeakCase.status.in_(
                tuple(_ACTIONABLE) + (CaseStatus.PARTIALLY_RECOVERED,)
            )
        )
        .with_for_update()
    ).all()

    out: list[RevenueLeakCase] = []
    for case in rows:
        status = CaseStatus(case.status)
        is_b2b = LegType(case.leg_type) is LegType.B2B_RECEIVABLE
        if status is CaseStatus.PARTIALLY_RECOVERED and not is_b2b:
            continue  # PARTIALLY_RECOVERED is terminal for non-B2B legs
        at_risk = Decimal(str(case.amount_at_risk))
        if amount == at_risk or (is_b2b and _ZERO < amount < at_risk):
            out.append(case)

    if sub_id and len(out) > 1:
        # A subscription success carries its subscription id — prefer the case
        # whose context names it, if that disambiguates.
        named = [c for c in out if (c.context or {}).get("subscription_id") == sub_id]
        if len(named) == 1:
            return named
    return out


def _match_merged_set(
    session: Session, scope: TenantScope, counterparty_id: uuid.UUID, amount: Decimal
) -> tuple[Action, list[RevenueLeakCase]] | None:
    """A single `Action` covering 2+ of this counterparty's open cases whose
    combined `amount_at_risk` equals `amount` (a lump payment for a merged
    outreach). Case rows are `FOR UPDATE`."""
    open_cases = {
        c.case_id: c
        for c in session.scalars(
            scope.select(RevenueLeakCase)
            .where(RevenueLeakCase.counterparty_id == counterparty_id)
            .where(RevenueLeakCase.superseded_by_case_id.is_(None))
            .where(
                RevenueLeakCase.status.in_(
                    tuple(_ACTIONABLE) + (CaseStatus.PARTIALLY_RECOVERED,)
                )
            )
            .with_for_update()
        ).all()
    }
    if len(open_cases) < 2:
        return None
    action_ids = session.scalars(
        select(ActionCase.action_id)
        .where(ActionCase.case_id.in_(list(open_cases)))
        .group_by(ActionCase.action_id)
        .having(func.count(func.distinct(ActionCase.case_id)) >= 2)
    ).all()
    for aid in action_ids:
        rows = session.scalars(
            select(ActionCase).where(ActionCase.action_id == aid)
        ).all()
        cids = [r.case_id for r in rows]
        if not all(cid in open_cases for cid in cids):
            continue
        cases = [open_cases[cid] for cid in cids]
        total = sum((Decimal(str(c.amount_at_risk)) for c in cases), Decimal("0"))
        if total == amount:
            return session.get(Action, aid), cases
    return None


def _try_self_paid_cancel(
    session: Session,
    scope: TenantScope,
    counterparty_id: uuid.UUID,
    amount: Decimal,
    event: Event,
    *,
    now: datetime,
) -> ReconcileOutcome:
    """§7.1.4 — no open (actionable) case matched. If a pre-diagnosis case does,
    the customer self-paid before Torque could act: close it CANCELLED /
    SELF_RECOVERED. Otherwise there is nothing Torque tracked to reconcile."""
    case = session.scalars(
        scope.select(RevenueLeakCase)
        .where(RevenueLeakCase.counterparty_id == counterparty_id)
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
        .where(RevenueLeakCase.status.in_(tuple(_PRE_DIAGNOSIS)))
        .where(RevenueLeakCase.amount_at_risk == amount)
        .with_for_update()
    ).first()
    if case is None:
        return ReconcileOutcome.NO_MATCH

    # The whole close is one unit; `module7_writer` must stay open across every
    # flush that carries the `recovery_type` / `recovered_amount` change (the
    # guard re-checks on each flush, INV-06).
    with module7_writer(session):
        transition_case(
            session, case, CaseStatus.CANCELLED,
            trigger="customer_self_paid", actor=Actor.SYSTEM,
        )
        case.recovery_type = RecoveryType.SELF_RECOVERED
        case.recovered_amount = amount
        case.closed_at = now
        _write_reconciled_event(session, case, amount, RecoveryType.SELF_RECOVERED)
        human_queue.remove_for_case(session, case)
        session.flush()
    return ReconcileOutcome.SELF_PAID_CANCELLED


# --- recovery application (§7.2) ---------------------------------------


def _apply_recovery(
    session: Session,
    case: RevenueLeakCase,
    applied_amount: Decimal,
    event: Event,
    recovery_type: RecoveryType,
    *,
    now: datetime,
) -> ReconcileOutcome:
    status = CaseStatus(case.status)
    if status not in _ACTIONABLE and status is not CaseStatus.PARTIALLY_RECOVERED:
        return ReconcileOutcome.NOOP  # already closed / not reconcilable

    is_b2b = LegType(case.leg_type) is LegType.B2B_RECEIVABLE
    at_risk = Decimal(str(case.amount_at_risk))
    applied = (
        Decimal(str(applied_amount))
        if is_b2b
        else min(Decimal(str(applied_amount)), at_risk)
    )

    if is_b2b and _ZERO < applied < at_risk:
        return _apply_b2b_partial(session, case, applied, event, recovery_type, now=now)

    # full recovery — one unit; `module7_writer` open across every flush (INV-06).
    with module7_writer(session):
        if is_b2b:
            _settle_all_invoices(session, case)
        if status is CaseStatus.PARTIALLY_RECOVERED:
            # B2B only (guarded above): PARTIALLY_RECOVERED has no direct →
            # RECOVERED edge — hop back through PLAYBOOK_ACTIVE (both legal, B2B).
            transition_case(
                session, case, CaseStatus.PLAYBOOK_ACTIVE,
                trigger="reconciliation_final_settlement", actor=Actor.SYSTEM,
            )
        transition_case(
            session, case, CaseStatus.RECOVERED,
            trigger="payment_reconciled", actor=Actor.SYSTEM,
        )
        case.recovery_type = recovery_type
        # §7.2 "recovered_amount = amount_at_risk" for a single full payment;
        # a B2B case closed by a final partial accumulates onto its prior
        # partials so the total is the full original balance.
        case.recovered_amount = (case.recovered_amount or _ZERO) + min(applied, at_risk)
        case.closed_at = now
        _write_reconciled_event(session, case, applied, recovery_type)
        human_queue.remove_for_case(session, case)
        session.flush()
    return ReconcileOutcome.RECOVERED


def _apply_b2b_partial(
    session: Session,
    case: RevenueLeakCase,
    applied: Decimal,
    event: Event,
    recovery_type: RecoveryType,
    *,
    now: datetime,
) -> ReconcileOutcome:
    _apply_to_invoices(session, case, applied)
    new_total = _outstanding_total(session, case)

    with module7_writer(session):
        case.amount_at_risk = new_total  # INV-33: amount_at_risk == Σ outstanding
        case.recovery_type = recovery_type
        case.recovered_amount = (case.recovered_amount or _ZERO) + applied

        if new_total == _ZERO:
            case.closed_at = now
            if CaseStatus(case.status) is CaseStatus.PARTIALLY_RECOVERED:
                transition_case(
                    session, case, CaseStatus.PLAYBOOK_ACTIVE,
                    trigger="reconciliation_final_settlement", actor=Actor.SYSTEM,
                )
            transition_case(
                session, case, CaseStatus.RECOVERED,
                trigger="payment_reconciled", actor=Actor.SYSTEM,
            )
            _write_reconciled_event(session, case, applied, recovery_type)
            human_queue.remove_for_case(session, case)
            session.flush()
            return ReconcileOutcome.RECOVERED

        if CaseStatus(case.status) is not CaseStatus.PARTIALLY_RECOVERED:
            transition_case(
                session, case, CaseStatus.PARTIALLY_RECOVERED,
                trigger="payment_reconciled", actor=Actor.SYSTEM,
            )
        _write_reconciled_event(session, case, applied, recovery_type)
        session.flush()
    return ReconcileOutcome.PARTIALLY_RECOVERED


def _apply_to_invoices(session: Session, case: RevenueLeakCase, amount: Decimal) -> None:
    """Waterfall a payment across the case's invoices, oldest due-date first."""
    remaining = Decimal(str(amount))
    invoices = session.scalars(
        TenantScope(session, case.merchant_id)
        .select(B2BInvoice)
        .where(B2BInvoice.case_id == case.case_id)
        .where(B2BInvoice.outstanding_amount > 0)
        .order_by(B2BInvoice.due_date.asc(), B2BInvoice.invoice_id.asc())
        .with_for_update()
    ).all()
    for inv in invoices:
        if remaining <= _ZERO:
            break
        take = min(remaining, Decimal(str(inv.outstanding_amount)))
        inv.outstanding_amount = Decimal(str(inv.outstanding_amount)) - take
        remaining -= take
    session.flush()


def _settle_all_invoices(session: Session, case: RevenueLeakCase) -> None:
    for inv in session.scalars(
        TenantScope(session, case.merchant_id)
        .select(B2BInvoice)
        .where(B2BInvoice.case_id == case.case_id)
        .with_for_update()
    ).all():
        inv.outstanding_amount = _ZERO
    session.flush()


def _outstanding_total(session: Session, case: RevenueLeakCase) -> Decimal:
    total = session.scalar(
        TenantScope(session, case.merchant_id)
        .select(B2BInvoice)
        .where(B2BInvoice.case_id == case.case_id)
        .with_only_columns(func.coalesce(func.sum(B2BInvoice.outstanding_amount), 0))
    )
    return Decimal(str(total or 0))


# --- attribution helpers --------------------------------------------------


def _torque_acted_within_window(
    session: Session, case: RevenueLeakCase, *, now: datetime
) -> bool:
    """§7.1.2 — did Torque execute any `Action` for this case within the
    attribution window (default 24h) before reconciliation? Blocked actions
    (`executed_at IS NULL`) do not count."""
    hours = get_policy().attribution_window_hours
    window_start = now - timedelta(hours=hours)
    n = session.scalar(
        TenantScope(session, case.merchant_id)
        .select(Action)
        .join(ActionCase, ActionCase.action_id == Action.action_id)
        .where(ActionCase.case_id == case.case_id)
        .where(Action.executed_at.is_not(None))
        .where(Action.executed_at >= window_start)
        .with_only_columns(func.count())
    )
    return bool(n and n > 0)


def _find_merged_action(session: Session, case_ids: list[uuid.UUID]) -> Action | None:
    """A single `Action` whose `ActionCase` set covers **all** `case_ids` — the
    Outreach Coordinator's merged outreach (§4.4 / §7.1.3)."""
    want = len(set(case_ids))
    action_ids = session.scalars(
        select(ActionCase.action_id)
        .where(ActionCase.case_id.in_(case_ids))
        .group_by(ActionCase.action_id)
        .having(func.count(func.distinct(ActionCase.case_id)) == want)
    ).all()
    if not action_ids:
        return None
    return session.scalars(
        select(Action)
        .where(Action.action_id.in_(action_ids))
        .order_by(Action.executed_at.desc().nullslast(), Action.created_at.desc())
    ).first()


def _resplit_credit_weight(
    session: Session, action: Action, cases: list[RevenueLeakCase]
) -> None:
    """§7.1.3 — re-weight `action`'s `ActionCase` rows proportional to each case's
    `amount_at_risk`, primary row taking the exact remainder so Σ ==
    `Decimal('1.00000')` (INV-12 re-validates on flush)."""
    by_id = {c.case_id: Decimal(str(c.amount_at_risk or 0)) for c in cases}
    rows = session.scalars(
        select(ActionCase).where(ActionCase.action_id == action.action_id)
    ).all()
    total = sum((by_id.get(r.case_id, _ZERO) for r in rows), Decimal("0"))
    primary = next(r for r in rows if r.is_primary)
    others = [r for r in rows if not r.is_primary]
    acc = Decimal("0")
    for r in others:
        if total > 0:
            w = (by_id.get(r.case_id, _ZERO) / total).quantize(_W_QUANT)
        else:
            w = (_ONE / len(rows)).quantize(_W_QUANT)
        r.credit_weight = w
        acc += w
    primary.credit_weight = _ONE - acc
    session.flush()


def _most_recently_actioned(
    session: Session, cases: list[RevenueLeakCase]
) -> RevenueLeakCase:
    """The ambiguous-multi-match tie-break: the case with the latest executed
    `Action`, falling back to the latest `opened_at`."""
    def _last_action(case: RevenueLeakCase) -> datetime | None:
        return session.scalar(
            TenantScope(session, case.merchant_id)
            .select(Action)
            .join(ActionCase, ActionCase.action_id == Action.action_id)
            .where(ActionCase.case_id == case.case_id)
            .where(Action.executed_at.is_not(None))
            .with_only_columns(func.max(Action.executed_at))
        )

    _epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return max(
        cases,
        key=lambda c: (_last_action(c) or _epoch, c.opened_at or _epoch),
    )


def _write_reconciled_event(
    session: Session,
    case: RevenueLeakCase,
    recovered_amount: Decimal,
    recovery_type: RecoveryType,
) -> None:
    append_case_event(
        session,
        case_id=case.case_id,
        event_type=CaseEventType.PAYMENT_RECONCILED,
        payload={
            "recovered_amount": recovered_amount,
            "recovery_type": recovery_type.value,
        },
        actor=Actor.SYSTEM,
        counterparty_id=case.counterparty_id,
    )


__all__ = ["ReconcileOutcome", "RECONCILE_EVENT_TYPES", "reconcile_event"]
