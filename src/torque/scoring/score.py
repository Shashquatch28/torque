"""The authoritative Module 8 recovery score — Blueprint §8.

    score = (probability × amount_at_risk) ÷ cost

`probability` is the Decision F cold-start benchmark with the §8.2 warm-start
adjustment (`torque.scoring.benchmarks`); `cost` is the forward intervention cost
(`torque.scoring.cost`); `amount_at_risk` is the case column. All monetary
arithmetic is exact `Decimal`.

**There is exactly one implementation of this formula.** Every consumer — the
Outreach Coordinator's priority ordering, the human queue's priority, Module 9
reporting, the future dashboard's top-at-risk view — reads it from here (via the
`torque.coordination.outreach_coordinator.priority()` seam, D-098 / D-113). The
formula is never re-derived inside a consumer.

The `RecoveryScore` result is structured so the formula can be *shown*, not just
applied (§8.7): probability × amount ÷ cost = score, plus a plain-language "Why:"
(leg, age bucket, benchmark %, whether relationship history adjusted it, the next
intervention channel).

**Recompute cadence (§8.5 / D-112).** `score_case` writes the score onto the
case (`recovery_score`, `recovery_score_breakdown`, `recovery_score_updated_at` —
no `CaseEvent`, no status change). It is called on: case creation (every leg's
ingestion path), diagnosis completion (`torque.diagnosis.engine`), and once daily
for every open case (`recompute_open_cases`, wired to Celery beat). Terminal /
closed cases are never (re)scored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.enums import CaseStatus, LegType
from torque.exceptions import RecoveryScoreError
from torque.models import B2BInvoice, MerchantCounterparty, RevenueLeakCase
from torque.scoring import benchmarks
from torque.scoring.cost import CostBreakdown, compute_cost
from torque.state_machine import is_terminal

_SCORE_QUANT = Decimal("0.0001")
_ZERO = Decimal("0")

#: Statuses that are always terminal regardless of leg (the SQL pre-filter for
#: the daily sweep; B2B `PARTIALLY_RECOVERED` still counts as open and is kept).
_ALWAYS_TERMINAL = (
    CaseStatus.RECOVERED,
    CaseStatus.EXHAUSTED,
    CaseStatus.CANCELLED,
    CaseStatus.WRITTEN_OFF,
)


@dataclass(frozen=True)
class RecoveryScore:
    """The recovery priority score for one case, with every input exposed so the
    calculation can be rendered (§8.7)."""

    case_id: str
    score: Decimal

    probability: Decimal          # final, warm-adjusted, bounded [0, 1]
    base_probability: Decimal     # Decision F cold-start lookup value
    warm_start_applied: bool
    warm_start_multiplier: Decimal
    promise_keeping_rate: float | None

    amount_at_risk: Decimal

    raw_cost: Decimal             # Σ priced rate-card rates for the next step
    effective_cost: Decimal       # max(raw_cost, floor) — the divisor
    cost_floor_applied: bool
    cost_basis: str
    cost_channels: tuple[str, ...]

    leg_type: str
    amount_bucket: str
    days_since_failure: float
    bucket_label: str
    next_step_action_type: str | None
    next_step_source: str
    computed_at: str

    # --- rendering -------------------------------------------------------

    _LEG_PHRASE = {
        LegType.SUBSCRIPTION_FAILURE: "Subscription failure",
        LegType.PAYMENT_DEGRADATION: "Payment degradation",
        LegType.CHECKOUT_ABANDONMENT: "Checkout abandonment",
        LegType.B2B_RECEIVABLE: "B2B invoice",
    }

    @staticmethod
    def _plain(value: Decimal) -> str:
        """Trailing-zero-stripped decimal for display (0.55000 → '0.55')."""
        normalized = value.normalize()
        # avoid scientific notation for whole numbers (1E+2 → 100)
        return f"{normalized:f}"

    def explain(self) -> dict:
        """The §8.7 UI shape: the four numbers plus a "Why:" bullet list."""
        leg_phrase = self._LEG_PHRASE.get(LegType(self.leg_type), self.leg_type)
        why = [
            leg_phrase,
            f"{self.bucket_label} old",
            f"{self.base_probability * 100:.0f}% benchmark recovery probability",
        ]
        if self.warm_start_applied:
            direction = (
                "up" if self.warm_start_multiplier > 1 else "down"
                if self.warm_start_multiplier < 1 else "unchanged"
            )
            why.append(
                f"Adjusted by relationship history "
                f"(×{self.warm_start_multiplier}, {direction})"
            )
        if self.next_step_action_type:
            channel = self.cost_channels[0] if self.cost_channels else "no channel"
            why.append(f"Next intervention: {channel}")
        elif self.cost_basis == "FLOOR_NO_PLAYBOOK":
            why.append("Next intervention: not yet planned")
        return {
            "probability": self._plain(self.probability),
            "amount_at_risk": str(self.amount_at_risk),
            "expected_cost": self._plain(self.effective_cost),
            "priority_score": self._plain(self.score),
            "why": why,
        }

    def to_dict(self) -> dict:
        """Full serialisation for the `recovery_score_breakdown` JSONB column."""
        return {
            "case_id": self.case_id,
            "score": str(self.score),
            "probability": str(self.probability),
            "base_probability": str(self.base_probability),
            "warm_start_applied": self.warm_start_applied,
            "warm_start_multiplier": str(self.warm_start_multiplier),
            "promise_keeping_rate": self.promise_keeping_rate,
            "amount_at_risk": str(self.amount_at_risk),
            "raw_cost": str(self.raw_cost),
            "effective_cost": str(self.effective_cost),
            "cost_floor_applied": self.cost_floor_applied,
            "cost_basis": self.cost_basis,
            "cost_channels": list(self.cost_channels),
            "leg_type": self.leg_type,
            "amount_bucket": self.amount_bucket,
            "days_since_failure": self.days_since_failure,
            "bucket_label": self.bucket_label,
            "next_step_action_type": self.next_step_action_type,
            "next_step_source": self.next_step_source,
            "computed_at": self.computed_at,
            "explain": self.explain(),
        }


# --- inputs -------------------------------------------------------------


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _days_since_failure(
    session: Session, case: RevenueLeakCase, *, now: datetime
) -> float:
    """`days_since_failure` for the cold-start lookup.

    * B2B: live days overdue — `max(now − due_date)` across the case's invoices,
      floored at the ingested `days_overdue` so it never regresses; the daily
      recompute ages this naturally (§8.5).
    * other legs: wall-clock age of the case (`now − opened_at`).
    """
    if LegType(case.leg_type) is LegType.B2B_RECEIVABLE:
        scope = TenantScope(session, case.merchant_id)
        invoices = session.scalars(
            scope.select(B2BInvoice).where(B2BInvoice.case_id == case.case_id)
        ).all()
        if invoices:
            live = max(
                max((now.date() - inv.due_date).days, int(inv.days_overdue or 0))
                for inv in invoices
            )
            return float(max(live, 0))
    opened = _aware(case.opened_at) or _aware(case.created_at) or now
    return max((now - opened).total_seconds() / 86400.0, 0.0)


def _promise_keeping_rate(session: Session, case: RevenueLeakCase) -> float | None:
    scope = TenantScope(session, case.merchant_id)
    mc = session.scalars(
        scope.select(MerchantCounterparty).where(
            MerchantCounterparty.counterparty_id == case.counterparty_id
        )
    ).first()
    return mc.promise_keeping_rate if mc is not None else None


# --- the formula ------------------------------------------------------


def compute_recovery_score(
    session: Session, case: RevenueLeakCase, *, now: datetime | None = None
) -> RecoveryScore:
    """`(probability × amount_at_risk) ÷ cost` for one case, fully explained.

    Deterministic given `(case state, related rows, now)`. Does not write
    anything — see `score_case` for persistence."""
    now = _aware(now) or datetime.now(UTC)

    amount = case.amount_at_risk
    amount_dec = _ZERO if amount is None else Decimal(str(amount))
    if amount_dec < 0:
        raise RecoveryScoreError(
            f"case {case.case_id} has a negative amount_at_risk ({amount_dec})"
        )

    days = _days_since_failure(session, case, now=now)
    base_prob = benchmarks.cold_start_probability(
        case.leg_type, days, amount_at_risk=amount_dec
    )
    rate = _promise_keeping_rate(session, case)
    multiplier = benchmarks.warm_start_multiplier(rate)
    probability = benchmarks.adjusted_probability(base_prob, rate)

    cost: CostBreakdown = compute_cost(session, case)

    score = (
        (probability * amount_dec) / cost.effective_cost
    ).quantize(_SCORE_QUANT, rounding=ROUND_HALF_EVEN)

    return RecoveryScore(
        case_id=str(case.case_id),
        score=score,
        probability=probability,
        base_probability=base_prob,
        warm_start_applied=rate is not None,
        warm_start_multiplier=multiplier,
        promise_keeping_rate=rate,
        amount_at_risk=amount_dec,
        raw_cost=cost.raw_cost,
        effective_cost=cost.effective_cost,
        cost_floor_applied=cost.floor_applied,
        cost_basis=cost.cost_basis.value,
        cost_channels=cost.channels,
        leg_type=str(case.leg_type),
        amount_bucket=benchmarks.amount_bucket(amount_dec),
        days_since_failure=round(days, 4),
        bucket_label=benchmarks.bucket_label(case.leg_type, days),
        next_step_action_type=cost.next_step_action_type,
        next_step_source=cost.next_step_source.value,
        computed_at=now.isoformat(),
    )


# --- persistence + recompute cadence (§8.5) ---------------------------


def score_case(
    session: Session, case: RevenueLeakCase, *, now: datetime | None = None
) -> RecoveryScore | None:
    """Compute and persist the recovery score onto `case`. No-op (returns
    ``None``) for a terminal / closed case — those are excluded from scoring.
    Does **not** commit; the caller owns the transaction. Writes no `CaseEvent`
    and changes no status (the score is a derived column)."""
    if is_terminal(case.status, case.leg_type):
        return None
    now = _aware(now) or datetime.now(UTC)
    result = compute_recovery_score(session, case, now=now)
    case.recovery_score = result.score
    case.recovery_score_breakdown = result.to_dict()
    case.recovery_score_updated_at = now
    session.flush()
    return result


def recompute_open_cases(
    session: Session, *, merchant_id: str | None = None, now: datetime | None = None
) -> int:
    """Daily recompute (§8.5 item 3): re-score every open case (optionally for one
    merchant) and refresh any `human_queue` entry's stored `priority` so the
    queue keeps ordering by the current score. Returns the number of cases
    (re)scored. The caller owns the transaction."""
    from torque.models import HumanQueueEntry

    now = _aware(now) or datetime.now(UTC)
    stmt = select(RevenueLeakCase).where(
        RevenueLeakCase.status.notin_([s.value for s in _ALWAYS_TERMINAL]),
        RevenueLeakCase.superseded_by_case_id.is_(None),
    )
    if merchant_id is not None:
        stmt = stmt.where(RevenueLeakCase.merchant_id == merchant_id)

    scored = 0
    for case in session.scalars(stmt).all():
        result = score_case(session, case, now=now)
        if result is None:
            continue
        scored += 1
        entry = session.scalars(
            TenantScope(session, case.merchant_id)
            .select(HumanQueueEntry)
            .where(HumanQueueEntry.case_id == case.case_id)
        ).first()
        if entry is not None:
            entry.priority = result.score
    session.flush()
    return scored


__all__ = [
    "RecoveryScore",
    "compute_recovery_score",
    "recompute_open_cases",
    "score_case",
]
