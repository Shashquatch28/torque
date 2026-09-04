"""Module 9b — Incrementality / causal measurement (Blueprint §6, §9.1).

Module 9 (descriptive) answers *what happened*. This module answers *what did
Torque's outreach cause* — the treatment-vs-control recovery-rate difference,
with a small-sample-honest confidence interval and the Blueprint's cross-merchant
SUTVA contamination adjustment shown **alongside**, never replacing, the headline.

Read-only. Every figure is derived on demand from `revenue_leak_case`
(`control_group`, `status`, `opened_at`, `counterparty_id`) — no persisted
aggregate, no migration: the cohort inputs (`Merchant_Counterparty.in_control_cohort`
→ the denormalised `RevenueLeakCase.control_group`) have existed since M1 and are
neither created nor modified here. Module 7 attribution and Module 9 descriptive
metrics are untouched.

Cohort membership — `RevenueLeakCase.control_group` (the per-case snapshot of the
counterparty's cohort for this merchant, kept in step by
`state_machine.sync_control_group`):

* `True`  — control: held out, receives no Torque outreach.
* `False` — treatment: eligible for the recovery playbook.
* `None`  — cohort not assigned → excluded from this report entirely.

Recovery (the success event) for causal measurement is **intent-to-treat and
attribution-agnostic**: a case counts as recovered iff its status is `RECOVERED`
or `CANCELLED` (customer self-paid). This deliberately differs from Module 9's
descriptive `recovery_rate`, which is Torque-*attributed* by design (D-116) — a
held-out control case that recovers does so by self-payment
(`recovery_type = SELF_RECOVERED`), so an attributed definition would pin the
control rate at ~0 and collapse "lift" into "treatment rate". Blueprint §6 itself
reasons about non-trivial control recovery rates. See D-133.

Confidence interval — Wilson score interval for each cohort proportion; Newcombe's
(1998) hybrid score interval for the difference of two independent proportions.
95% two-sided (`z = Φ⁻¹(0.975)`). See D-134.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from statistics import NormalDist

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.enums import CaseStatus, LegType
from torque.models import RevenueLeakCase
from torque.reporting.metrics import ReportWindow
from torque.reporting.schemas import (
    IncrementalityReport,
    LiftEstimate,
    ProportionCI,
    SutvaAdjustment,
)

#: Two-sided 95% — the conservative, universally-understood reporting default
#: (Blueprint gives no figure; D-134). A wider batch → a wider interval, shown
#: honestly rather than hidden.
_CONFIDENCE_LEVEL = Decimal("0.95")
_Z = Decimal(str(NormalDist().inv_cdf(0.975)))  # ≈ 1.959963984540054

_Q = Decimal("0.0001")  # 4 dp, matching Module 9's rate quantum
_ZERO = Decimal(0)
_ONE = Decimal(1)
_NEG_ONE = Decimal(-1)

#: Intent-to-treat success: the customer's at-risk money came back, by any means.
_RECOVERED_STATUSES = frozenset({CaseStatus.RECOVERED, CaseStatus.CANCELLED})

_LIFT_METHOD = "newcombe_wilson_hybrid_score"

_RECOVERY_DEFINITION = (
    "A case counts as recovered when its final status is RECOVERED or CANCELLED "
    "(customer self-paid) — intent-to-treat, regardless of attribution credit. "
    "This is broader than the dashboard's Torque-attributed recovery rate so the "
    "held-out control cohort has a meaningful self-recovery baseline."
)

_SUTVA_NOTE = (
    "Sensitivity view (Blueprint §6). A control counterparty that Torque is also "
    "treating for another merchant in this window can self-recover from that "
    "outreach's spillover, inflating the control rate and understating true lift. "
    "The adjusted figures drop every such control counterparty. Only the "
    "counterparty overlap is read across merchants — no other merchant's amounts, "
    "outcomes, counts, or identity. Shown alongside, never replacing, the headline."
)


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q, rounding=ROUND_HALF_EVEN)


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return low if value < low else high if value > high else value


def _wilson_raw(successes: int, total: int) -> tuple[Decimal, Decimal]:
    """Unclamped, unquantised Wilson score bounds. `total > 0` required."""
    n = Decimal(total)
    p = Decimal(successes) / n
    z2 = _Z * _Z
    denom = _ONE + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    margin = (_Z / denom) * (p * (_ONE - p) / n + z2 / (4 * n * n)).sqrt()
    return centre - margin, centre + margin


def wilson_interval(successes: int, total: int) -> tuple[Decimal | None, Decimal | None]:
    """Wilson score interval for a single proportion, clamped to [0, 1] and
    quantised to 4 dp. `total == 0` → `(None, None)` (undefined, never NaN)."""
    if total <= 0:
        return None, None
    low, high = _wilson_raw(successes, total)
    return _q(_clamp(low, _ZERO, _ONE)), _q(_clamp(high, _ZERO, _ONE))


def newcombe_difference(
    t_successes: int, t_total: int, c_successes: int, c_total: int
) -> tuple[Decimal | None, Decimal | None]:
    """Newcombe (1998) hybrid score interval for (treatment_rate − control_rate),
    built from the two Wilson intervals. Clamped to [-1, 1], quantised to 4 dp.
    Either cohort empty → `(None, None)`."""
    if t_total <= 0 or c_total <= 0:
        return None, None
    tp = Decimal(t_successes) / Decimal(t_total)
    cp = Decimal(c_successes) / Decimal(c_total)
    t_low, t_high = _wilson_raw(t_successes, t_total)
    c_low, c_high = _wilson_raw(c_successes, c_total)
    d = tp - cp
    lower = d - ((tp - t_low) ** 2 + (c_high - cp) ** 2).sqrt()
    upper = d + ((t_high - tp) ** 2 + (cp - c_low) ** 2).sqrt()
    return (
        _q(_clamp(lower, _NEG_ONE, _ONE)),
        _q(_clamp(upper, _NEG_ONE, _ONE)),
    )


def _proportion(successes: int, total: int) -> ProportionCI:
    rate = _q(Decimal(successes) / Decimal(total)) if total > 0 else None
    low, high = wilson_interval(successes, total)
    return ProportionCI(
        successes=successes, total=total, rate=rate, ci_low=low, ci_high=high
    )


def _lift(t_successes: int, t_total: int, c_successes: int, c_total: int) -> LiftEstimate:
    point = (
        _q(Decimal(t_successes) / Decimal(t_total) - Decimal(c_successes) / Decimal(c_total))
        if t_total > 0 and c_total > 0
        else None
    )
    low, high = newcombe_difference(t_successes, t_total, c_successes, c_total)
    return LiftEstimate(point=point, ci_low=low, ci_high=high, method=_LIFT_METHOD)


@dataclass(frozen=True)
class _CohortCase:
    counterparty_id: uuid.UUID
    control: bool
    recovered: bool


def _cohort_cases(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None,
    leg: LegType | str | None,
) -> list[_CohortCase]:
    """The merchant's own cohort-assigned, non-superseded cases in the window."""
    scope = TenantScope(session, merchant_id)
    stmt = scope.select(RevenueLeakCase).where(
        RevenueLeakCase.superseded_by_case_id.is_(None),
        RevenueLeakCase.control_group.is_not(None),
    )
    if leg is not None:
        stmt = stmt.where(RevenueLeakCase.leg_type == LegType(leg))
    if window is not None:
        stmt = window.apply(stmt, RevenueLeakCase.opened_at)
    rows = session.execute(
        stmt.with_only_columns(
            RevenueLeakCase.counterparty_id,
            RevenueLeakCase.control_group,
            RevenueLeakCase.status,
        )
    ).all()
    return [
        _CohortCase(
            counterparty_id=cp_id,
            control=bool(control_group),
            recovered=CaseStatus(str(status)) in _RECOVERED_STATUSES,
        )
        for cp_id, control_group, status in rows
    ]


def _contaminated_control_counterparties(
    session: Session,
    merchant_id: str,
    control_counterparty_ids: set[uuid.UUID],
    *,
    window: ReportWindow | None,
) -> set[uuid.UUID]:
    """Blueprint §6 cross-merchant contamination. Returns the subset of
    `control_counterparty_ids` that ALSO have a treatment case
    (`control_group = False`, non-superseded) at a **different** merchant with
    `opened_at` in the same window.

    This is the one deliberately cross-merchant read in the module. It is bounded
    both ways: the `IN (:control_counterparty_ids)` filter means the query can
    only ever return ids the caller already holds (its own control counterparties),
    and only `counterparty_id` is selected — never another merchant's id, case
    ids, amounts, statuses, or counts. The result is reduced to a `set` before it
    leaves this function; nothing merchant-B-specific reaches any response field.
    """
    if not control_counterparty_ids:
        return set()
    stmt = (
        select(RevenueLeakCase.counterparty_id)
        .where(RevenueLeakCase.merchant_id != merchant_id)
        .where(RevenueLeakCase.control_group.is_(False))
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
        .where(RevenueLeakCase.counterparty_id.in_(control_counterparty_ids))
        .distinct()
    )
    if window is not None:
        stmt = window.apply(stmt, RevenueLeakCase.opened_at)
    return set(session.scalars(stmt).all())


def incrementality_report(
    session: Session,
    merchant_id: str,
    *,
    window: ReportWindow | None = None,
    leg: LegType | str | None = None,
) -> IncrementalityReport:
    """The causal layer for `merchant_id` over the `opened_at` window (Blueprint
    §6 / §9.1). Tenant-scoped; read-only. See the module docstring for the
    cohort and recovery definitions."""
    cases = _cohort_cases(session, merchant_id, window=window, leg=leg)
    treatment_cases = [c for c in cases if not c.control]
    control_cases = [c for c in cases if c.control]

    t_x = sum(1 for c in treatment_cases if c.recovered)
    t_n = len(treatment_cases)
    c_x = sum(1 for c in control_cases if c.recovered)
    c_n = len(control_cases)

    # --- SUTVA sensitivity: drop contaminated control counterparties ---
    contaminated = _contaminated_control_counterparties(
        session,
        merchant_id,
        {c.counterparty_id for c in control_cases},
        window=window,
    )
    adjusted_control = [
        c for c in control_cases if c.counterparty_id not in contaminated
    ]
    adj_c_x = sum(1 for c in adjusted_control if c.recovered)
    adj_c_n = len(adjusted_control)

    sutva = SutvaAdjustment(
        contaminated_control_counterparties=len(contaminated),
        excluded_control_cases=c_n - adj_c_n,
        control=_proportion(adj_c_x, adj_c_n),
        lift=_lift(t_x, t_n, adj_c_x, adj_c_n),
        note=_SUTVA_NOTE,
    )

    return IncrementalityReport(
        merchant_id=merchant_id,
        opened_from=window.start if window else None,
        opened_to=window.end if window else None,
        leg_type=str(LegType(leg)) if leg is not None else None,
        window_basis="opened_at",
        confidence_level=_CONFIDENCE_LEVEL,
        z_value=_Z,
        recovery_definition=_RECOVERY_DEFINITION,
        treatment=_proportion(t_x, t_n),
        control=_proportion(c_x, c_n),
        lift=_lift(t_x, t_n, c_x, c_n),
        sutva=sutva,
    )


__all__ = [
    "incrementality_report",
    "newcombe_difference",
    "wilson_interval",
]
