"""Module 9 — recovery measurement (Blueprint §9).

Every figure is **derived on demand** from the authoritative domain tables
(`revenue_leak_case`, `action` / `action_case`, `b2b_invoice`, `case_event`,
`human_queue`). There is no persisted aggregate, no cache, no migration (D-114) —
so a reported number is always exactly what the live rows say, and it is
traceable straight through to case / action / reconciliation evidence (§9.8).

**Module 7 stays authoritative for attribution.** This module reads
`RevenueLeakCase.recovery_type` / `recovered_amount` (set only by reconciliation,
INV-53); it never re-matches payments or re-derives who gets credit (§9.3).

**Outcome-based (§9.1).** The headline is money recovered
(`recovery_type != SELF_RECOVERED`, D-116). `SELF_RECOVERED` money is reported
separately. Message / retry / playbook counts live in `OperationalReport`.

Every query is tenant-scoped (INV-01): tenant-scoped models go through
`TenantScope`; `case_event` (no `merchant_id`) is filtered by a join to
`revenue_leak_case.merchant_id`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.enums import ActionOutcome, BlockReason, CaseStatus, LegType, RecoveryType
from torque.models import (
    Action,
    ActionCase,
    B2BInvoice,
    CaseEvent,
    Counterparty,
    HumanQueueEntry,
    RevenueLeakCase,
)
from torque.reporting.schemas import (
    ActionSummary,
    ActivityEntry,
    ActivityFeed,
    BlockedReasonCount,
    CaseDetail,
    CaseEventEntry,
    CaseList,
    CaseListItem,
    EscalationReasonCount,
    FailedActionCount,
    HumanQueueItem,
    HumanQueueList,
    InterventionBreakdown,
    LegBreakdown,
    OperationalReport,
    OutcomeBreakdown,
    RecoveryReport,
    RecoverySummary,
    TerminalStatusCount,
    TimeBucket,
    TopCaseItem,
    TopCaseList,
)
from torque.state_machine import is_terminal

_ZERO = Decimal("0")
_RATE_Q = Decimal("0.0001")
_MONEY_Q = Decimal("0.01")

#: `recovery_type` values that count as a Torque-caused recovery (§9.1 /
#: D-116 — everything except `SELF_RECOVERED`).
_TORQUE_CREDITED = frozenset({RecoveryType.AGENT_ASSISTED, RecoveryType.AMBIGUOUS})

#: Deliberately-closed statuses (recovered / self-paid / written off).
_RESOLVED_CLOSED = frozenset(
    {CaseStatus.RECOVERED, CaseStatus.CANCELLED, CaseStatus.WRITTEN_OFF}
)

#: Statuses that are terminal regardless of leg — the SQL pre-filter for
#: "top at-risk" (open cases Torque can still act on). Non-B2B
#: `PARTIALLY_RECOVERED` is also terminal and is dropped in Python afterwards.
_ALWAYS_TERMINAL = frozenset(
    {
        CaseStatus.RECOVERED,
        CaseStatus.CANCELLED,
        CaseStatus.WRITTEN_OFF,
        CaseStatus.EXHAUSTED,
    }
)

_BUCKETS = ("day", "week", "month")


# --- window -------------------------------------------------------------


@dataclass(frozen=True)
class ReportWindow:
    """A half-open `[start, end)` filter. Applied to `opened_at` for batch
    membership (summary / breakdowns) and to `closed_at` for the time series.
    Half-open so adjacent windows never double-count a boundary row. Naive
    datetimes are read as UTC (project storage convention)."""

    start: datetime | None = None
    end: datetime | None = None

    @staticmethod
    def _aware(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    def apply(self, stmt: Select, column) -> Select:
        s, e = self._aware(self.start), self._aware(self.end)
        if s is not None:
            stmt = stmt.where(column >= s)
        if e is not None:
            stmt = stmt.where(column < e)
        return stmt


# --- in-scope case materialisation -----------------------------------


@dataclass(frozen=True)
class _CaseRow:
    case_id: uuid.UUID
    leg_type: str
    status: str
    amount_at_risk: Decimal
    recovery_type: str | None
    recovered_amount: Decimal | None
    opened_at: datetime | None
    closed_at: datetime | None
    recovery_score: Decimal | None

    @property
    def is_b2b(self) -> bool:
        return LegType(self.leg_type) is LegType.B2B_RECEIVABLE

    @property
    def torque_credited(self) -> bool:
        return self.recovery_type is not None and RecoveryType(
            self.recovery_type
        ) in _TORQUE_CREDITED

    @property
    def self_recovered(self) -> bool:
        return (
            self.recovery_type is not None
            and RecoveryType(self.recovery_type) is RecoveryType.SELF_RECOVERED
        ) or CaseStatus(self.status) is CaseStatus.CANCELLED

    @property
    def status_is_terminal(self) -> bool:
        return is_terminal(self.status, self.leg_type)

    @property
    def is_recovered_case(self) -> bool:
        return CaseStatus(self.status) is CaseStatus.RECOVERED and self.torque_credited

    @property
    def is_unresolved(self) -> bool:
        st = CaseStatus(self.status)
        if st in _RESOLVED_CLOSED:
            return False
        # non-B2B PARTIALLY_RECOVERED is terminal → resolved; B2B keeps dunning.
        if st is CaseStatus.PARTIALLY_RECOVERED and not self.is_b2b:
            return False
        return True


def _scoped_cases(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None,
    leg: LegType | str | None,
) -> list[_CaseRow]:
    scope = TenantScope(session, merchant_id)
    stmt = scope.select(RevenueLeakCase).where(
        RevenueLeakCase.superseded_by_case_id.is_(None)
    )
    if leg is not None:
        stmt = stmt.where(RevenueLeakCase.leg_type == LegType(leg))
    if window is not None:
        stmt = window.apply(stmt, RevenueLeakCase.opened_at)
    rows = session.scalars(stmt).all()
    return [
        _CaseRow(
            case_id=c.case_id,
            leg_type=str(c.leg_type),
            status=str(c.status),
            amount_at_risk=Decimal(str(c.amount_at_risk or 0)),
            recovery_type=str(c.recovery_type) if c.recovery_type else None,
            recovered_amount=(
                Decimal(str(c.recovered_amount)) if c.recovered_amount is not None else None
            ),
            opened_at=c.opened_at,
            closed_at=c.closed_at,
            recovery_score=(
                Decimal(str(c.recovery_score)) if c.recovery_score is not None else None
            ),
        )
        for c in rows
    ]


def _b2b_original_by_case(
    session: Session, merchant_id: str, case_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """`{case_id: Σ B2BInvoice.original_amount}` — the immutable B2B exposure
    (D-115). `case.amount_at_risk` is a mutating residual (INV-55), so the
    invoice table is the authoritative source for the recovery-rate denominator."""
    if not case_ids:
        return {}
    scope = TenantScope(session, merchant_id)
    rows = session.execute(
        scope.select(B2BInvoice)
        .where(B2BInvoice.case_id.in_(case_ids))
        .with_only_columns(
            B2BInvoice.case_id, func.coalesce(func.sum(B2BInvoice.original_amount), 0)
        )
        .group_by(B2BInvoice.case_id)
    ).all()
    return {cid: Decimal(str(total)) for cid, total in rows}


def _revenue_at_risk(row: _CaseRow, b2b_orig: dict[uuid.UUID, Decimal]) -> Decimal:
    if row.is_b2b:
        return b2b_orig.get(row.case_id, row.amount_at_risk)
    return row.amount_at_risk


@dataclass(frozen=True)
class _ActionFact:
    case_id: uuid.UUID
    action_type: str
    outcome: str
    block_reason: str | None
    executed: bool


def _action_facts(
    session: Session, merchant_id: str, case_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[_ActionFact]]:
    """Per-case action facts, joined through `ActionCase` so a merged outreach's
    secondary cases are counted too. Tenant-scoped via `Action.merchant_id`."""
    if not case_ids:
        return {}
    scope = TenantScope(session, merchant_id)
    rows = session.execute(
        scope.select(Action)
        .join(ActionCase, ActionCase.action_id == Action.action_id)
        .where(ActionCase.case_id.in_(case_ids))
        .with_only_columns(
            ActionCase.case_id,
            Action.action_type,
            Action.outcome,
            Action.block_reason,
            Action.executed_at,
        )
    ).all()
    out: dict[uuid.UUID, list[_ActionFact]] = defaultdict(list)
    for case_id, atype, outcome, block_reason, executed_at in rows:
        out[case_id].append(
            _ActionFact(
                case_id=case_id,
                action_type=str(atype),
                outcome=str(outcome),
                block_reason=str(block_reason) if block_reason else None,
                executed=executed_at is not None,
            )
        )
    return out


def _rate(numerator: Decimal | int, denominator: Decimal | int) -> Decimal:
    d = Decimal(str(denominator))
    if d <= 0:
        return _ZERO
    return (Decimal(str(numerator)) / d).quantize(_RATE_Q, rounding=ROUND_HALF_EVEN)


def _money(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_MONEY_Q, rounding=ROUND_HALF_EVEN)


# --- Module 10 shared helpers -------------------------------------


def _probability_from_breakdown(breakdown: dict | None) -> Decimal | None:
    """The Module 8 `probability` (0..1) out of the stored `recovery_score_
    breakdown`. The dashboard renders it; it is never recomputed here."""
    if not breakdown:
        return None
    raw = breakdown.get("probability")
    try:
        return Decimal(str(raw)) if raw is not None else None
    except (ValueError, ArithmeticError):
        return None


def _next_intervention(breakdown: dict | None) -> str | None:
    if not breakdown:
        return None
    return breakdown.get("next_step_action_type")


def _counterparty_labels(
    session: Session, counterparty_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """`{counterparty_id: display label}` for the merchant's own customers.
    `Counterparty` is the global PII table — the merchant may see its own
    customers' names; a missing name falls back to a short id. No cross-tenant
    exposure: the ids come only from the merchant's own cases."""
    if not counterparty_ids:
        return {}
    rows = session.scalars(
        select(Counterparty).where(Counterparty.counterparty_id.in_(set(counterparty_ids)))
    ).all()
    out: dict[uuid.UUID, str] = {}
    for cp in rows:
        name = (cp.name or "").strip()
        out[cp.counterparty_id] = name or f"Customer {str(cp.counterparty_id)[:8]}"
    return out


# --- summary (§9.2 core metrics) -----------------------------------


def recovery_summary(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None = None,
    leg: LegType | str | None = None,
) -> RecoverySummary:
    cases = _scoped_cases(session, merchant_id, window=window, leg=leg)
    case_ids = [c.case_id for c in cases]
    b2b_orig = _b2b_original_by_case(
        session, merchant_id, [c.case_id for c in cases if c.is_b2b]
    )
    facts = _action_facts(session, merchant_id, case_ids)

    revenue_at_risk = _ZERO
    recovered_amount = _ZERO
    self_recovered_amount = _ZERO
    unresolved_amount = _ZERO
    blocked_amount = _ZERO
    deferred_amount = _ZERO

    recovered_cases = self_recovered_cases = partial_cases = 0
    unresolved_cases = exhausted_cases = written_off_cases = 0

    for c in cases:
        rar = _revenue_at_risk(c, b2b_orig)
        revenue_at_risk += rar

        if c.torque_credited and c.recovered_amount is not None:
            recovered_amount += c.recovered_amount
        if c.self_recovered and c.recovered_amount is not None:
            self_recovered_amount += c.recovered_amount

        st = CaseStatus(c.status)
        if c.is_recovered_case:
            recovered_cases += 1
        if c.self_recovered:
            self_recovered_cases += 1
        if st is CaseStatus.PARTIALLY_RECOVERED and c.is_b2b:
            partial_cases += 1
        if st is CaseStatus.WRITTEN_OFF:
            written_off_cases += 1
        if st is CaseStatus.EXHAUSTED:
            exhausted_cases += 1
        if c.is_unresolved:
            unresolved_cases += 1
            unresolved_amount += c.amount_at_risk

        cf = facts.get(c.case_id, [])
        if any(f.outcome == ActionOutcome.BLOCKED_BY_GUARDRAIL.value for f in cf):
            blocked_amount += rar
        if any(
            f.block_reason == BlockReason.OUTREACH_COORDINATOR_DEFERRED.value for f in cf
        ):
            deferred_amount += rar

    total_action_cost = _executed_action_cost(session, merchant_id, case_ids)
    escalated = _escalated_case_ids(session, merchant_id, case_ids)

    n = len(cases)
    return RecoverySummary(
        merchant_id=merchant_id,
        opened_from=window.start if window else None,
        opened_to=window.end if window else None,
        leg_type=str(LegType(leg)) if leg is not None else None,
        case_count=n,
        revenue_at_risk=_money(revenue_at_risk),
        recovered_amount=_money(recovered_amount),
        self_recovered_amount=_money(self_recovered_amount),
        unresolved_amount=_money(unresolved_amount),
        blocked_amount=_money(blocked_amount),
        deferred_amount=_money(deferred_amount),
        total_action_cost=_money(total_action_cost),
        recovered_case_count=recovered_cases,
        self_recovered_case_count=self_recovered_cases,
        partially_recovered_case_count=partial_cases,
        unresolved_case_count=unresolved_cases,
        exhausted_case_count=exhausted_cases,
        written_off_case_count=written_off_cases,
        escalated_case_count=len(escalated),
        recovery_rate=_rate(recovered_cases, n),
        amount_recovery_rate=_rate(recovered_amount, revenue_at_risk),
        cost_efficiency_ratio=(
            _rate(recovered_amount, total_action_cost)
            if total_action_cost > 0
            else None
        ),
    )


def _executed_action_cost(
    session: Session, merchant_id: str, case_ids: list[uuid.UUID]
) -> Decimal:
    if not case_ids:
        return _ZERO
    scope = TenantScope(session, merchant_id)
    total = session.scalar(
        scope.select(Action)
        .where(Action.primary_case_id.in_(case_ids))
        .where(Action.executed_at.is_not(None))
        .with_only_columns(func.coalesce(func.sum(Action.cost), 0))
    )
    return Decimal(str(total or 0))


def _escalated_case_ids(
    session: Session, merchant_id: str, case_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    if not case_ids:
        return set()
    scope = TenantScope(session, merchant_id)
    in_status = set(
        session.scalars(
            scope.select(RevenueLeakCase)
            .where(RevenueLeakCase.case_id.in_(case_ids))
            .where(RevenueLeakCase.status == CaseStatus.ESCALATED_TO_HUMAN)
            .with_only_columns(RevenueLeakCase.case_id)
        ).all()
    )
    in_queue = set(
        session.scalars(
            scope.select(HumanQueueEntry)
            .where(HumanQueueEntry.case_id.in_(case_ids))
            .with_only_columns(HumanQueueEntry.case_id)
        ).all()
    )
    return in_status | in_queue


# --- by leg (§9.1 / §9.5) ----------------------------------------


def recovery_by_leg(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None = None,
) -> list[LegBreakdown]:
    cases = _scoped_cases(session, merchant_id, window=window, leg=None)
    b2b_orig = _b2b_original_by_case(
        session, merchant_id, [c.case_id for c in cases if c.is_b2b]
    )
    by_leg: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "rec": 0, "rar": _ZERO, "recovered": _ZERO, "self": _ZERO}
    )
    for c in cases:
        b = by_leg[c.leg_type]
        b["n"] += 1
        b["rar"] += _revenue_at_risk(c, b2b_orig)
        if c.is_recovered_case:
            b["rec"] += 1
        if c.torque_credited and c.recovered_amount is not None:
            b["recovered"] += c.recovered_amount
        if c.self_recovered and c.recovered_amount is not None:
            b["self"] += c.recovered_amount

    return [
        LegBreakdown(
            leg_type=leg,
            cases_attempted=b["n"],
            cases_recovered=b["rec"],
            revenue_at_risk=_money(b["rar"]),
            recovered_amount=_money(b["recovered"]),
            self_recovered_amount=_money(b["self"]),
            recovery_rate=_rate(b["rec"], b["n"]),
            amount_recovery_rate=_rate(b["recovered"], b["rar"]),
        )
        for leg, b in sorted(by_leg.items())
    ]


# --- by intervention / action type (§9.5 secondary view) --------


def recovery_by_action_type(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None = None,
) -> list[InterventionBreakdown]:
    cases = _scoped_cases(session, merchant_id, window=window, leg=None)
    case_ids = [c.case_id for c in cases]
    by_id = {c.case_id: c for c in cases}
    b2b_orig = _b2b_original_by_case(
        session, merchant_id, [c.case_id for c in cases if c.is_b2b]
    )
    facts = _action_facts(session, merchant_id, case_ids)

    # action_type -> set of case_ids that executed it
    used: dict[str, set[uuid.UUID]] = defaultdict(set)
    for cid, cf in facts.items():
        for f in cf:
            if f.executed:
                used[f.action_type].add(cid)

    out: list[InterventionBreakdown] = []
    for atype, cids in sorted(used.items()):
        rows = [by_id[cid] for cid in cids if cid in by_id]
        rar = sum((_revenue_at_risk(r, b2b_orig) for r in rows), _ZERO)
        recovered = sum(
            (r.recovered_amount for r in rows if r.torque_credited and r.recovered_amount),
            _ZERO,
        )
        rec_n = sum(1 for r in rows if r.is_recovered_case)
        out.append(
            InterventionBreakdown(
                action_type=atype,
                cases_attempted=len(rows),
                cases_recovered=rec_n,
                revenue_at_risk=_money(rar),
                recovered_amount=_money(recovered),
                recovery_rate=_rate(rec_n, len(rows)),
                amount_recovery_rate=_rate(recovered, rar),
            )
        )
    return out


# --- by recovery type / outcome (§9.2) --------------------------


def recovery_by_recovery_type(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None = None,
) -> list[OutcomeBreakdown]:
    cases = _scoped_cases(session, merchant_id, window=window, leg=None)
    agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "amt": _ZERO})
    for c in cases:
        key = c.recovery_type or "UNATTRIBUTED"
        agg[key]["n"] += 1
        if c.recovered_amount is not None:
            agg[key]["amt"] += c.recovered_amount
    return [
        OutcomeBreakdown(
            recovery_type=key, case_count=v["n"], recovered_amount=_money(v["amt"])
        )
        for key, v in sorted(agg.items())
    ]


# --- recovery over time (§9.2 / D-119) -------------------------


def recovery_over_time(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None = None,
    bucket: str = "day",
) -> list[TimeBucket]:
    if bucket not in _BUCKETS:
        raise ValueError(f"bucket must be one of {_BUCKETS}, got {bucket!r}")
    scope = TenantScope(session, merchant_id)
    b = func.date_trunc(bucket, RevenueLeakCase.closed_at)
    stmt = (
        scope.select(RevenueLeakCase)
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
        .where(RevenueLeakCase.status == CaseStatus.RECOVERED)
        .where(RevenueLeakCase.recovery_type.in_(tuple(_TORQUE_CREDITED)))
        .where(RevenueLeakCase.closed_at.is_not(None))
        .with_only_columns(
            b.label("bucket_start"),
            func.count(),
            func.coalesce(func.sum(RevenueLeakCase.recovered_amount), 0),
        )
        .group_by(b)
        .order_by(b)
    )
    if window is not None:
        stmt = window.apply(stmt, RevenueLeakCase.closed_at)
    rows = session.execute(stmt).all()
    return [
        TimeBucket(
            bucket_start=bstart,
            bucket=bucket,
            recovered_case_count=int(n),
            recovered_amount=_money(Decimal(str(amt))),
        )
        for bstart, n, amt in rows
    ]


# --- operational / exception reporting (§9.7) -----------------


def operational_exceptions(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None = None,
) -> OperationalReport:
    cases = _scoped_cases(session, merchant_id, window=window, leg=None)
    case_ids = [c.case_id for c in cases]
    by_id = {c.case_id: c for c in cases}
    b2b_orig = _b2b_original_by_case(
        session, merchant_id, [c.case_id for c in cases if c.is_b2b]
    )
    scope = TenantScope(session, merchant_id)

    # blocked actions grouped by reason (§9.1 exception list) — via ActionCase so
    # a merged action counts for every participating in-scope case.
    blocked_rows = session.execute(
        scope.select(Action)
        .join(ActionCase, ActionCase.action_id == Action.action_id)
        .where(ActionCase.case_id.in_(case_ids or [uuid.uuid4()]))
        .where(Action.outcome == ActionOutcome.BLOCKED_BY_GUARDRAIL)
        .with_only_columns(Action.block_reason, ActionCase.case_id)
    ).all()
    blk_actions: dict[str, int] = defaultdict(int)
    blk_cases: dict[str, set[uuid.UUID]] = defaultdict(set)
    for reason, cid in blocked_rows:
        r = str(reason) if reason else "UNKNOWN"
        blk_actions[r] += 1
        blk_cases[r].add(cid)
    blocked_by_reason = [
        BlockedReasonCount(
            block_reason=r,
            action_count=blk_actions[r],
            case_count=len(blk_cases[r]),
            revenue_at_risk=_money(
                sum(
                    (
                        _revenue_at_risk(by_id[cid], b2b_orig)
                        for cid in blk_cases[r]
                        if cid in by_id
                    ),
                    _ZERO,
                )
            ),
        )
        for r in sorted(blk_actions)
    ]
    deferred_cases = blk_cases.get(BlockReason.OUTREACH_COORDINATOR_DEFERRED.value, set())
    deferred_action_count = blk_actions.get(
        BlockReason.OUTREACH_COORDINATOR_DEFERRED.value, 0
    )

    # failed / no-response executed actions by type
    failed_rows = session.execute(
        scope.select(Action)
        .join(ActionCase, ActionCase.action_id == Action.action_id)
        .where(ActionCase.case_id.in_(case_ids or [uuid.uuid4()]))
        .where(Action.outcome.in_((ActionOutcome.FAILED, ActionOutcome.NO_RESPONSE)))
        .with_only_columns(Action.action_type, Action.outcome, func.count())
        .group_by(Action.action_type, Action.outcome)
    ).all()
    failed_by_type = [
        FailedActionCount(
            action_type=str(atype), outcome=str(outcome), action_count=int(n)
        )
        for atype, outcome, n in sorted(failed_rows, key=lambda r: (str(r[0]), str(r[1])))
    ]

    escalated = _escalated_case_ids(session, merchant_id, case_ids)
    esc_rows = session.execute(
        scope.select(HumanQueueEntry)
        .where(HumanQueueEntry.case_id.in_(case_ids or [uuid.uuid4()]))
        .with_only_columns(HumanQueueEntry.reason, func.count())
        .group_by(HumanQueueEntry.reason)
    ).all()
    escalations_by_reason = [
        EscalationReasonCount(reason=str(reason), case_count=int(n))
        for reason, n in sorted(esc_rows, key=lambda r: str(r[0]))
    ]

    # terminal cases by status
    term: dict[str, dict] = defaultdict(lambda: {"n": 0, "rar": _ZERO, "rec": _ZERO})
    for c in cases:
        if c.status_is_terminal:
            t = term[c.status]
            t["n"] += 1
            t["rar"] += _revenue_at_risk(c, b2b_orig)
            if c.recovered_amount is not None and c.torque_credited:
                t["rec"] += c.recovered_amount
    terminal_by_status = [
        TerminalStatusCount(
            status=st,
            case_count=v["n"],
            revenue_at_risk=_money(v["rar"]),
            recovered_amount=_money(v["rec"]),
        )
        for st, v in sorted(term.items())
    ]

    return OperationalReport(
        merchant_id=merchant_id,
        opened_from=window.start if window else None,
        opened_to=window.end if window else None,
        blocked_by_reason=blocked_by_reason,
        deferred_action_count=deferred_action_count,
        deferred_case_count=len(deferred_cases),
        failed_by_type=failed_by_type,
        escalated_case_count=len(escalated),
        escalations_by_reason=escalations_by_reason,
        terminal_by_status=terminal_by_status,
    )


# --- batch report bundle (§9.4) --------------------------------


def recovery_report(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None = None,
    leg: LegType | str | None = None,
) -> RecoveryReport:
    return RecoveryReport(
        summary=recovery_summary(session, merchant_id, window=window, leg=leg),
        by_leg=recovery_by_leg(session, merchant_id, window=window),
        by_recovery_type=recovery_by_recovery_type(session, merchant_id, window=window),
        operational=operational_exceptions(session, merchant_id, window=window),
    )


# --- case-level drill-down (§9.8 / §9.10) -----------------------


def list_cases(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None = None,
    leg: LegType | str | None = None,
    status: CaseStatus | str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CaseList:
    scope = TenantScope(session, merchant_id)
    base = scope.select(RevenueLeakCase).where(
        RevenueLeakCase.superseded_by_case_id.is_(None)
    )
    if leg is not None:
        base = base.where(RevenueLeakCase.leg_type == LegType(leg))
    if status is not None:
        base = base.where(RevenueLeakCase.status == CaseStatus(status))
    if window is not None:
        base = window.apply(base, RevenueLeakCase.opened_at)

    total = int(
        session.scalar(base.with_only_columns(func.count()).order_by(None)) or 0
    )
    rows = session.scalars(
        base.order_by(RevenueLeakCase.opened_at.desc(), RevenueLeakCase.case_id)
        .limit(limit)
        .offset(offset)
    ).all()
    b2b_ids = [
        c.case_id for c in rows if LegType(c.leg_type) is LegType.B2B_RECEIVABLE
    ]
    b2b_orig = _b2b_original_by_case(session, merchant_id, b2b_ids)
    items = [
        CaseListItem(
            case_id=str(c.case_id),
            leg_type=str(c.leg_type),
            status=str(c.status),
            opened_at=c.opened_at,
            closed_at=c.closed_at,
            revenue_at_risk=_money(
                b2b_orig.get(c.case_id, Decimal(str(c.amount_at_risk or 0)))
                if LegType(c.leg_type) is LegType.B2B_RECEIVABLE
                else Decimal(str(c.amount_at_risk or 0))
            ),
            recovery_type=str(c.recovery_type) if c.recovery_type else None,
            recovered_amount=(
                _money(Decimal(str(c.recovered_amount)))
                if c.recovered_amount is not None
                else None
            ),
        )
        for c in rows
    ]
    return CaseList(
        merchant_id=merchant_id, total=total, limit=limit, offset=offset, items=items
    )


def case_detail(
    session: Session, merchant_id: str, case_id: uuid.UUID
) -> CaseDetail | None:
    scope = TenantScope(session, merchant_id)
    c = scope.get(RevenueLeakCase, case_id)
    if c is None:
        return None

    b2b_orig = _b2b_original_by_case(
        session,
        merchant_id,
        [c.case_id] if LegType(c.leg_type) is LegType.B2B_RECEIVABLE else [],
    )
    rar = (
        b2b_orig.get(c.case_id, Decimal(str(c.amount_at_risk or 0)))
        if LegType(c.leg_type) is LegType.B2B_RECEIVABLE
        else Decimal(str(c.amount_at_risk or 0))
    )

    action_rows = session.execute(
        scope.select(Action)
        .join(ActionCase, ActionCase.action_id == Action.action_id)
        .where(ActionCase.case_id == case_id)
        .with_only_columns(
            Action.action_type,
            Action.channel,
            Action.outcome,
            Action.block_reason,
            Action.executed_at,
            Action.cost,
            ActionCase.credit_weight,
        )
        .order_by(Action.created_at.asc())
    ).all()
    actions = [
        ActionSummary(
            action_type=str(atype),
            channel=channel,
            outcome=str(outcome),
            block_reason=str(block_reason) if block_reason else None,
            executed_at=executed_at,
            cost=Decimal(str(cost)) if cost is not None else None,
            credit_weight=Decimal(str(weight)) if weight is not None else None,
        )
        for atype, channel, outcome, block_reason, executed_at, cost, weight in action_rows
    ]

    hq = session.scalars(
        scope.select(HumanQueueEntry).where(HumanQueueEntry.case_id == case_id)
    ).first()
    label = _counterparty_labels(session, [c.counterparty_id]).get(
        c.counterparty_id, "Customer"
    )
    breakdown = dict(c.recovery_score_breakdown) if c.recovery_score_breakdown else None

    return CaseDetail(
        case_id=str(c.case_id),
        merchant_id=merchant_id,
        leg_type=str(c.leg_type),
        status=str(c.status),
        is_terminal=is_terminal(c.status, c.leg_type),
        opened_at=c.opened_at,
        closed_at=c.closed_at,
        counterparty_label=label,
        root_cause_code=c.root_cause_code,
        diagnosis_confidence=c.diagnosis_confidence,
        amount_at_risk=_money(Decimal(str(c.amount_at_risk or 0))),
        revenue_at_risk=_money(rar),
        recovery_type=str(c.recovery_type) if c.recovery_type else None,
        recovered_amount=(
            _money(Decimal(str(c.recovered_amount))) if c.recovered_amount is not None else None
        ),
        recovery_score=(
            Decimal(str(c.recovery_score)) if c.recovery_score is not None else None
        ),
        recovery_probability=_probability_from_breakdown(breakdown),
        recovery_score_breakdown=breakdown,
        in_human_queue=hq is not None,
        human_queue_reason=hq.reason if hq is not None else None,
        escalation_resolution=c.escalation_resolution,
        escalation_resolved_by=c.escalation_resolved_by,
        actions=actions,
    )


# --- Module 10: top-at-risk, human queue, activity feed ---------


def top_at_risk_cases(
    session: Session, merchant_id: str, *, limit: int = 20
) -> TopCaseList:
    """§10.4 — open cases ranked by Module 8's authoritative `recovery_score`
    (`ORDER BY recovery_score DESC NULLS LAST`). The frontend renders this order
    verbatim; it never re-derives `(probability × amount_at_risk) ÷ cost`."""
    scope = TenantScope(session, merchant_id)
    rows = session.scalars(
        scope.select(RevenueLeakCase)
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
        .where(
            RevenueLeakCase.status.notin_([s.value for s in _ALWAYS_TERMINAL])
        )
        .order_by(
            RevenueLeakCase.recovery_score.desc().nullslast(),
            RevenueLeakCase.opened_at.desc(),
        )
        .limit(limit)
    ).all()
    # non-B2B PARTIALLY_RECOVERED is terminal — drop it (it slipped the SQL filter)
    rows = [r for r in rows if not is_terminal(r.status, r.leg_type)]
    labels = _counterparty_labels(session, [r.counterparty_id for r in rows])
    queued = _queued_case_ids(session, merchant_id, [r.case_id for r in rows])
    escalated = {
        r.case_id for r in rows if CaseStatus(r.status) is CaseStatus.ESCALATED_TO_HUMAN
    } | queued
    return TopCaseList(
        merchant_id=merchant_id,
        limit=limit,
        items=[
            TopCaseItem(
                case_id=str(r.case_id),
                counterparty_label=labels.get(r.counterparty_id, "Customer"),
                leg_type=str(r.leg_type),
                status=str(r.status),
                amount_at_risk=_money(Decimal(str(r.amount_at_risk or 0))),
                recovery_probability=_probability_from_breakdown(r.recovery_score_breakdown),
                recovery_score=(
                    Decimal(str(r.recovery_score)) if r.recovery_score is not None else None
                ),
                next_intervention=_next_intervention(r.recovery_score_breakdown),
                in_human_queue=r.case_id in queued,
                escalated=r.case_id in escalated,
            )
            for r in rows
        ],
    )


def _queued_case_ids(
    session: Session, merchant_id: str, case_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    if not case_ids:
        return set()
    scope = TenantScope(session, merchant_id)
    return set(
        session.scalars(
            scope.select(HumanQueueEntry)
            .where(HumanQueueEntry.case_id.in_(case_ids))
            .with_only_columns(HumanQueueEntry.case_id)
        ).all()
    )


def human_queue_list(session: Session, merchant_id: str) -> HumanQueueList:
    """§10.7 — the Agent Console queue: every `human_queue` entry for the
    merchant joined to its case, ordered by the entry's stored `priority`
    (the Module 8 seam) then `enqueued_at` — the same order Module 6's
    `human_queue.list_for_merchant` produces. No frontend sort."""
    scope = TenantScope(session, merchant_id)
    entries = session.scalars(
        scope.select(HumanQueueEntry).order_by(
            HumanQueueEntry.priority.desc(), HumanQueueEntry.enqueued_at.asc()
        )
    ).all()
    if not entries:
        return HumanQueueList(merchant_id=merchant_id, items=[])
    by_case = {
        c.case_id: c
        for c in session.scalars(
            scope.select(RevenueLeakCase).where(
                RevenueLeakCase.case_id.in_([e.case_id for e in entries])
            )
        ).all()
    }
    labels = _counterparty_labels(
        session, [c.counterparty_id for c in by_case.values()]
    )
    items: list[HumanQueueItem] = []
    for e in entries:
        c = by_case.get(e.case_id)
        if c is None:
            continue
        items.append(
            HumanQueueItem(
                case_id=str(e.case_id),
                counterparty_label=labels.get(c.counterparty_id, "Customer"),
                leg_type=str(c.leg_type),
                status=str(c.status),
                reason=e.reason,
                priority=Decimal(str(e.priority)),
                enqueued_at=e.enqueued_at,
                amount_at_risk=_money(Decimal(str(c.amount_at_risk or 0))),
                recovery_score=(
                    Decimal(str(c.recovery_score)) if c.recovery_score is not None else None
                ),
                recovery_probability=_probability_from_breakdown(c.recovery_score_breakdown),
            )
        )
    return HumanQueueList(merchant_id=merchant_id, items=items)


def recent_activity(
    session: Session, merchant_id: str, *, limit: int = 50
) -> ActivityFeed:
    """§10.17 live feed — the merchant's most recent `CaseEvent`s (newest
    `event_seq_id` first). Tenant-scoped by a join to
    `revenue_leak_case.merchant_id` (`case_event` has no `merchant_id`)."""
    rows = session.execute(
        select(
            CaseEvent.event_seq_id,
            CaseEvent.case_id,
            RevenueLeakCase.leg_type,
            RevenueLeakCase.status,
            CaseEvent.event_type,
            CaseEvent.actor,
            CaseEvent.timestamp,
            CaseEvent.reasoning,
            CaseEvent.payload,
        )
        .join(RevenueLeakCase, RevenueLeakCase.case_id == CaseEvent.case_id)
        .where(RevenueLeakCase.merchant_id == merchant_id)
        .order_by(CaseEvent.event_seq_id.desc())
        .limit(limit)
    ).all()
    return ActivityFeed(
        merchant_id=merchant_id,
        items=[
            ActivityEntry(
                event_seq_id=int(seq),
                case_id=str(cid),
                leg_type=str(leg),
                case_status=str(status),
                event_type=str(etype),
                actor=str(actor),
                timestamp=ts,
                reasoning=reasoning,
                payload=dict(payload or {}),
            )
            for seq, cid, leg, status, etype, actor, ts, reasoning, payload in rows
        ],
    )


def case_event_stream(
    session: Session, merchant_id: str, case_id: uuid.UUID
) -> list[CaseEventEntry] | None:
    """§9.2 explainability panel — the case's `CaseEvent` stream in
    `event_seq_id` order. `case_event` has no `merchant_id`; the case is
    verified to belong to `merchant_id` first (returns `None` otherwise)."""
    scope = TenantScope(session, merchant_id)
    if scope.get(RevenueLeakCase, case_id) is None:
        return None
    rows = session.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case_id)
        .order_by(CaseEvent.event_seq_id.asc())
    ).all()
    return [
        CaseEventEntry(
            event_seq_id=e.event_seq_id,
            event_type=str(e.event_type),
            actor=str(e.actor),
            timestamp=e.timestamp,
            reasoning=e.reasoning,
            payload=dict(e.payload or {}),
        )
        for e in rows
    ]


__all__ = [
    "ReportWindow",
    "case_detail",
    "case_event_stream",
    "human_queue_list",
    "list_cases",
    "operational_exceptions",
    "recent_activity",
    "recovery_by_action_type",
    "recovery_by_leg",
    "recovery_by_recovery_type",
    "recovery_over_time",
    "recovery_report",
    "recovery_summary",
    "top_at_risk_cases",
]
