"""Module 9 — the reporting result contract (Blueprint §9).

These pydantic models are BOTH the return type of `torque.reporting.metrics`
and the response schema of `torque.api.reporting`. Every money field is a
`Decimal` (rupees, 2 dp); every figure is derived on demand from the
authoritative domain tables — there is no persisted aggregate (D-114).

**Outcome-based, not activity-based (§9.1).** The headline is
`recovered_amount` — money Torque actually brought back, per Module 7's
`recovery_type` (`AGENT_ASSISTED` / `AMBIGUOUS`; `SELF_RECOVERED` is reported
separately, never folded in — D-116). Message / retry / playbook *counts* are
operational context (`OperationalReport`), not the business result.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class RecoverySummary(_Model):
    """Merchant- or batch-level totals (§9.2 core metrics)."""

    merchant_id: str
    #: Batch window applied to `opened_at` (`None` bound = unbounded).
    opened_from: datetime | None = None
    opened_to: datetime | None = None
    leg_type: str | None = None  # set when the summary is filtered to one leg

    case_count: int
    #: Σ per-case revenue-at-risk (D-115: non-B2B `amount_at_risk`; B2B
    #: `Σ B2BInvoice.original_amount`). The recovery-rate denominator.
    revenue_at_risk: Decimal

    #: Σ `recovered_amount` where `recovery_type` is Torque-credited
    #: (`!= SELF_RECOVERED`, not null) — the north-star number (D-116).
    recovered_amount: Decimal
    #: Σ `recovered_amount` where `recovery_type = SELF_RECOVERED` — the customer
    #: paid without Torque. Reported, never folded into `recovered_amount`.
    self_recovered_amount: Decimal
    #: Σ current `amount_at_risk` of cases still unresolved (open or EXHAUSTED).
    unresolved_amount: Decimal
    #: Σ revenue-at-risk of cases that hit ≥1 BLOCKED_BY_GUARDRAIL action (D-118).
    blocked_amount: Decimal
    #: Σ revenue-at-risk of cases with ≥1 OUTREACH_COORDINATOR_DEFERRED action.
    deferred_amount: Decimal
    #: Σ executed `Action.cost` (still nullable/unpopulated by Module 5 — this
    #: figure is currently ~0; §9.1 cost-efficiency).
    total_action_cost: Decimal

    recovered_case_count: int
    self_recovered_case_count: int
    partially_recovered_case_count: int  # B2B, still open, has banked partials
    unresolved_case_count: int
    exhausted_case_count: int
    written_off_case_count: int
    escalated_case_count: int  # ESCALATED_TO_HUMAN ∪ human_queue

    #: Blueprint §9.1 "recovered cases ÷ total cases" (0 when no cases).
    recovery_rate: Decimal
    #: `recovered_amount ÷ revenue_at_risk` — the demo headline (0 when no risk).
    amount_recovery_rate: Decimal
    #: `recovered_amount ÷ total_action_cost`, or `None` when cost is 0.
    cost_efficiency_ratio: Decimal | None


class LegBreakdown(_Model):
    """§9.1 "₹ recovered by leg" + §9.5 intervention-effectiveness columns."""

    leg_type: str
    cases_attempted: int
    cases_recovered: int
    revenue_at_risk: Decimal
    recovered_amount: Decimal
    self_recovered_amount: Decimal
    recovery_rate: Decimal          # cases_recovered ÷ cases_attempted
    amount_recovery_rate: Decimal   # recovered_amount ÷ revenue_at_risk


class InterventionBreakdown(_Model):
    """Recovery grouped by the `ActionType` Torque executed (§9.5 secondary
    view). A case appears under EVERY action type it used, so rows sum to more
    than the de-duplicated `LegBreakdown` totals — see `overlaps` on the
    response envelope."""

    action_type: str
    cases_attempted: int
    cases_recovered: int
    revenue_at_risk: Decimal
    recovered_amount: Decimal
    recovery_rate: Decimal
    amount_recovery_rate: Decimal


class OutcomeBreakdown(_Model):
    """§9.2 "recovery by outcome" — grouped by `recovery_type`
    (`AGENT_ASSISTED` / `SELF_RECOVERED` / `AMBIGUOUS` / `UNATTRIBUTED`)."""

    recovery_type: str
    case_count: int
    recovered_amount: Decimal


class TimeBucket(_Model):
    """§9.2 "recovery over time" — one `date_trunc(bucket, closed_at)` bucket
    (UTC), Torque-credited recoveries only (D-119)."""

    bucket_start: datetime
    bucket: str  # "day" | "week" | "month"
    recovered_case_count: int
    recovered_amount: Decimal


class BlockedReasonCount(_Model):
    block_reason: str
    action_count: int
    case_count: int
    revenue_at_risk: Decimal


class FailedActionCount(_Model):
    action_type: str
    outcome: str  # FAILED | NO_RESPONSE
    action_count: int


class EscalationReasonCount(_Model):
    reason: str
    case_count: int


class TerminalStatusCount(_Model):
    status: str
    case_count: int
    revenue_at_risk: Decimal
    recovered_amount: Decimal


class OperationalReport(_Model):
    """§9.7 — where Torque deliberately stopped, deferred, failed, or escalated.
    Consumes the authoritative outcomes from Modules 5–7; defines no guardrail
    logic of its own."""

    merchant_id: str
    opened_from: datetime | None = None
    opened_to: datetime | None = None

    #: §9.1 exception list — every BLOCKED_BY_GUARDRAIL action, grouped by reason.
    blocked_by_reason: list[BlockedReasonCount]
    #: Actions blocked with `OUTREACH_COORDINATOR_DEFERRED` (the only defer that
    #: writes an Action — D-099; pure timing defers are not countable here).
    deferred_action_count: int
    deferred_case_count: int
    #: Executed actions that did not land — FAILED / NO_RESPONSE, by type.
    failed_by_type: list[FailedActionCount]
    #: Cases currently waiting on a human (ESCALATED_TO_HUMAN ∪ human_queue).
    escalated_case_count: int
    escalations_by_reason: list[EscalationReasonCount]
    #: Every terminal case, grouped by terminal `status`.
    terminal_by_status: list[TerminalStatusCount]


class ActionSummary(_Model):
    action_type: str
    channel: str | None
    outcome: str
    block_reason: str | None
    executed_at: datetime | None
    cost: Decimal | None
    credit_weight: Decimal | None  # this case's ActionCase weight on the action


class CaseDetail(_Model):
    """§9.10 case-level drill-down — enough to trace every reported number back
    to the case / actions / reconciliation evidence (§9.8). Module 10 (§10.5)
    additionally surfaces `recovery_score_breakdown` (Module 8's structured
    "WHY THIS CASE?" panel) and the human-resolution fields."""

    case_id: str
    merchant_id: str
    leg_type: str
    status: str
    is_terminal: bool
    opened_at: datetime | None
    closed_at: datetime | None

    counterparty_label: str
    root_cause_code: str | None
    diagnosis_confidence: float | None

    amount_at_risk: Decimal        # current (residual, for B2B)
    revenue_at_risk: Decimal       # original exposure (D-115)
    recovery_type: str | None
    recovered_amount: Decimal | None
    recovery_score: Decimal | None
    #: `probability` parsed out of the Module 8 breakdown (0..1), for the panel.
    recovery_probability: Decimal | None
    #: The full Module 8 `RecoveryScore.to_dict()` — probability × amount ÷ cost
    #: and the "why" lines (§8.7). Rendered verbatim; the frontend invents nothing.
    recovery_score_breakdown: dict | None

    in_human_queue: bool
    human_queue_reason: str | None
    escalation_resolution: str | None
    escalation_resolved_by: str | None

    actions: list[ActionSummary]


class TopCaseItem(_Model):
    """§10.4 top-at-risk ranked row. Ordered by Module 8's authoritative
    `recovery_score` (backend `ORDER BY … DESC`); the frontend never re-derives
    `(probability × amount_at_risk) ÷ cost`."""

    case_id: str
    counterparty_label: str
    leg_type: str
    status: str
    amount_at_risk: Decimal
    recovery_probability: Decimal | None
    recovery_score: Decimal | None
    next_intervention: str | None  # breakdown.next_step_action_type
    in_human_queue: bool
    escalated: bool


class TopCaseList(_Model):
    merchant_id: str
    limit: int
    items: list[TopCaseItem]


class HumanQueueItem(_Model):
    """§10.7 Agent Console queue row — the `human_queue` entry (Module 6),
    joined to its case. Ordered by the queue's own `priority` (Module 8 seam),
    not a frontend sort."""

    case_id: str
    counterparty_label: str
    leg_type: str
    status: str
    reason: str          # HumanQueueReason
    priority: Decimal    # the stored economic priority (Module 8 seam)
    enqueued_at: datetime
    amount_at_risk: Decimal
    recovery_score: Decimal | None
    recovery_probability: Decimal | None


class HumanQueueList(_Model):
    merchant_id: str
    items: list[HumanQueueItem]


class ActivityEntry(_Model):
    """§10.17 live feed — one recent `CaseEvent` across the merchant's cases,
    newest `event_seq_id` first."""

    event_seq_id: int
    case_id: str
    leg_type: str
    case_status: str
    event_type: str
    actor: str
    timestamp: datetime
    reasoning: str | None
    payload: dict


class ActivityFeed(_Model):
    merchant_id: str
    items: list[ActivityEntry]


class CaseListItem(_Model):
    case_id: str
    leg_type: str
    status: str
    opened_at: datetime | None
    closed_at: datetime | None
    revenue_at_risk: Decimal
    recovery_type: str | None
    recovered_amount: Decimal | None


class CaseList(_Model):
    merchant_id: str
    total: int
    limit: int
    offset: int
    items: list[CaseListItem]


class CaseEventEntry(_Model):
    """§9.2 explainability panel — one row of the case's `CaseEvent` stream, in
    `event_seq_id` order. `reasoning` is the human-readable text, `payload` the
    structured detail. No computation — the stream IS the explanation."""

    event_seq_id: int
    event_type: str
    actor: str
    timestamp: datetime
    reasoning: str | None
    payload: dict


class RecoveryReport(_Model):
    """§9.4 batch report — the bundle a merchant/UI asks for in one call:
    the summary plus the leg / outcome / operational breakdowns over one
    `opened_at` window."""

    summary: RecoverySummary
    by_leg: list[LegBreakdown]
    by_recovery_type: list[OutcomeBreakdown]
    operational: OperationalReport


# --- Module 9b: incrementality / causal measurement (§6 / §9.1) --------


class ProportionCI(_Model):
    """One cohort's recovery proportion with its Wilson score interval.
    `total == 0` ⇒ `rate` / `ci_low` / `ci_high` are `None` (undefined — never
    NaN or an out-of-range bound)."""

    successes: int
    total: int
    rate: Decimal | None       # successes / total (∈ [0, 1])
    ci_low: Decimal | None     # Wilson score lower bound (∈ [0, 1])
    ci_high: Decimal | None    # Wilson score upper bound (∈ [0, 1])


class LiftEstimate(_Model):
    """treatment recovery rate − control recovery rate, with a small-sample CI
    for the difference of two independent proportions (Newcombe 1998 hybrid
    score interval built from the two Wilson intervals). `point` / bounds are
    `None` when either cohort is empty."""

    point: Decimal | None      # ∈ [-1, 1]
    ci_low: Decimal | None     # ∈ [-1, 1]
    ci_high: Decimal | None    # ∈ [-1, 1]
    method: str = "newcombe_wilson_hybrid_score"


class SutvaAdjustment(_Model):
    """Blueprint §6 cross-merchant contamination sensitivity. The control cohort
    with every counterparty that is ALSO in a treatment cohort at another
    merchant in the same window removed; the treatment cohort is unchanged.
    Presented ALONGSIDE the headline lift, never instead of it."""

    contaminated_control_counterparties: int
    excluded_control_cases: int
    control: ProportionCI      # control cohort after removing contaminated counterparties
    lift: LiftEstimate         # treatment (unchanged) vs the adjusted control
    note: str


class IncrementalityReport(_Model):
    """Module 9b (Blueprint §6 / §9.1) — the CAUSAL layer: the estimated
    incremental effect of Torque's outreach, distinct from the DESCRIPTIVE
    recovery report. A point estimate with an honest interval — not a proof of
    causality. Recovery here is intent-to-treat (`status ∈ {RECOVERED,
    CANCELLED}`), deliberately broader than the dashboard's attributed
    `recovery_rate` so the held-out control has a baseline (see
    `recovery_definition`; D-133)."""

    merchant_id: str
    opened_from: datetime | None = None
    opened_to: datetime | None = None
    leg_type: str | None = None
    #: The window column — the Module 9 convention, stated so the UI can label it.
    window_basis: str = "opened_at"
    confidence_level: Decimal          # 0.95 (two-sided)
    z_value: Decimal                   # Φ⁻¹(0.975)
    recovery_definition: str

    treatment: ProportionCI
    control: ProportionCI
    lift: LiftEstimate

    sutva: SutvaAdjustment
