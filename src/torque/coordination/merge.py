"""The Outreach Coordinator's live **merge** path — Blueprint Part A §5 / §4.4.

> if two cases from the same merchant are both awaiting their next outreach step
> for the same counterparty at the same time, they merge into a single `Action`
> with both `case_id`s represented via `ActionCase` rows.

This runs inside one poll pass (`torque.execution.scheduler.execute_due_jobs`),
where every candidate `ScheduledJob` is already claimed under one
`FOR UPDATE SKIP LOCKED` transaction — so "claim both due jobs atomically under
the existing locking model" (Q-C) is satisfied with no new concurrency
machinery.

**Trigger.** Two or more runs for the same `(merchant_id, counterparty_id)` whose
current step is a non-terminal customer-outreach action and whose timers are both
due (`fire_at <= now`).

**Primary.** The higher-`priority` case owns the merged `Action` (priority is the
Module 8 seam — `amount_at_risk` today, D-098). Ties break by `case_id` for
determinism.

**With a `multi_case_template`** — one `Action` (attributed to the primary run)
with one `ActionCase` per participating case, `credit_weight` proportional to
`amount_at_risk` and summing to exactly `Decimal("1.00000")`; every participating
run then advances on the send's outcome so none can re-fire.

**Without a `multi_case_template`** — the primary case's single-case action
executes normally; each secondary run is **deferred** (an `ACTION_BLOCKED` /
`OUTREACH_COORDINATOR_DEFERRED` row, its timer pushed forward, its step *not*
advanced) — never silently dropped (§4.4 / line 760).

**Residual race (documented).** The two stratified pollers (§5.6) claim disjoint
job sets. If a merge pair is split across the 10 s `PAYMENT_DEGRADATION` poller
and the 60 s other-legs poller — or across two concurrent workers of the same
stratum — neither sees both jobs, so no merge happens and the two cases each get
their own solo outreach. That is the un-merged baseline (two messages for two
cases), not a double-send of one case; `UNIQUE(run_id)` + `SKIP LOCKED` still
guarantee each step fires at most once. Widening this would require cross-stratum
coordination the blueprint's §5.6 fallback deliberately does not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from torque.coordination import outreach_coordinator as OC
from torque.enums import ActionOutcome, ActionType, Actor, BlockReason, PlaybookRunStatus
from torque.events import Attribution, write_action_and_event
from torque.execution import runner as R
from torque.execution import timing
from torque.execution.executor import ActionContext, channel_for, run_action
from torque.execution.rendering import multi_case_context, resolve_template
from torque.models import Action, Playbook, PlaybookRun, RevenueLeakCase, ScheduledJob
from torque.policy import traversal
from torque.policy.engine import resolve_effective_stopping_rules

#: A secondary run with no `multi_case_template` is deferred at least this far so
#: it cannot tight-loop against the same merge collision on the next poll.
_MERGE_DEFER_MIN_HOURS = 1.0

_QUANT = Decimal("0.00001")
_ONE = Decimal("1.00000")


@dataclass(frozen=True)
class _Item:
    job: ScheduledJob
    run: PlaybookRun
    case: RevenueLeakCase
    graph: dict
    node: dict
    rules: object  # StoppingRules


def _resolve_item(session: Session, job: ScheduledJob) -> _Item | None:
    """Load everything a merge decision needs for one claimed job, or `None` if
    the job is not merge-eligible (gone / terminal run / superseded case / a
    non-outreach or terminal step). Defensive: any lookup problem → not eligible,
    so the solo loop (with its poison-job isolation) handles it."""
    try:
        run = session.get(PlaybookRun, job.run_id)
        if run is None or PlaybookRunStatus(run.status) is not PlaybookRunStatus.RUNNING:
            return None
        case = session.get(RevenueLeakCase, run.case_id)
        if case is None or case.superseded_by_case_id is not None:
            return None
        pinned = session.get(Playbook, (run.playbook_id, run.playbook_version))
        if pinned is None:
            return None
        graph = pinned.steps_graph
        step_id = run.active_step_id
        node = traversal.node(graph, step_id)
        action_type = ActionType(node["action_template"]["type"])
        if action_type not in OC.OUTREACH_ACTIONS:
            return None
        if traversal.is_terminal(graph, step_id):
            return None
        rules = resolve_effective_stopping_rules(session, run)
        return _Item(job=job, run=run, case=case, graph=graph, node=node, rules=rules)
    except Exception:  # noqa: BLE001 — merge is best-effort; solo path is the fallback
        return None


def merge_groups(
    session: Session, jobs: list[ScheduledJob], *, now
) -> dict[tuple[str, object], list[_Item]]:
    """Group the claimed `jobs` by `(merchant_id, counterparty_id)`, keeping only
    groups of 2+ merge-eligible outreach jobs. Jobs not in a returned group are
    left for the solo execution loop."""
    if len(jobs) < 2:
        return {}
    by_key: dict[tuple[str, object], list[_Item]] = {}
    for job in jobs:
        item = _resolve_item(session, job)
        if item is None:
            continue
        key = (item.case.merchant_id, item.case.counterparty_id)
        by_key.setdefault(key, []).append(item)
    return {k: v for k, v in by_key.items() if len(v) >= 2}


def _ordered(items: list[_Item]) -> list[_Item]:
    """Primary first: highest `priority`, ties broken by `case_id` string."""
    return sorted(
        items, key=lambda it: (OC.priority(it.case), str(it.case.case_id)), reverse=True
    )


def _weights(cases: list[RevenueLeakCase]) -> list[Decimal]:
    """`credit_weight` per case: proportional to `amount_at_risk`, summing to
    exactly `Decimal("1.00000")`. `cases[0]` (the primary) takes the remainder so
    the sum is exact regardless of rounding."""
    n = len(cases)
    amounts = [Decimal(str(c.amount_at_risk or 0)) for c in cases]
    total = sum(amounts, Decimal("0"))
    if total <= 0:
        share = (_ONE / n).quantize(_QUANT)
        tail = [share] * (n - 1)
        return [(_ONE - sum(tail, Decimal("0"))), *tail]
    tail = [(amounts[i] / total).quantize(_QUANT) for i in range(1, n)]
    return [(_ONE - sum(tail, Decimal("0"))), *tail]


def execute_merged(session: Session, items: list[_Item], *, now) -> list[R.StepResult]:
    """Execute one merge group (>= 2 items, same merchant + counterparty). Runs
    inside the caller's per-group SAVEPOINT."""
    ordered = _ordered(items)
    primary, secondaries = ordered[0], ordered[1:]
    action_type = ActionType(primary.node["action_template"]["type"])
    template, defer_secondary = resolve_template(primary.node, case_count=len(ordered))

    if defer_secondary:
        return _execute_split(session, primary, secondaries, action_type, now=now)

    # --- merged send: one Action, one ActionCase per case ---------------------
    _ = multi_case_context([it.case for it in ordered])  # realised context (stub ignores)
    outcome = run_action(
        ActionContext(
            action_type=action_type,
            channel=channel_for(action_type),
            template=template,
        )
    )
    weights = _weights([it.case for it in ordered])
    attributions = [
        Attribution(
            case_id=it.case.case_id,
            is_primary=(i == 0),
            credit_weight=weights[i],
        )
        for i, it in enumerate(ordered)
    ]
    blocked = outcome is ActionOutcome.BLOCKED_BY_GUARDRAIL  # never, for the stub
    action = Action(
        merchant_id=primary.case.merchant_id,
        primary_case_id=primary.case.case_id,
        run_id=primary.run.run_id,
        action_type=action_type,
        channel=channel_for(action_type),
        executed_at=None if blocked else now,
        outcome=outcome,
        block_reason=None,
        cost=None,
    )
    write_action_and_event(
        session,
        action=action,
        actor=Actor.AGENT,
        attributions=attributions,
        counterparty_id=primary.case.counterparty_id,
    )

    edge = R._OUTCOME_TO_EDGE.get(outcome, "on_no_response")
    for it in ordered:
        R._advance(
            session, it.case, it.run, it.job, it.graph, it.node["id"], edge, outcome, now=now
        )
    return [R.StepResult.MERGED for _ in ordered]


def _execute_split(
    session: Session,
    primary: _Item,
    secondaries: list[_Item],
    action_type: ActionType,
    *,
    now,
) -> list[R.StepResult]:
    """No `multi_case_template`: the primary sends its single-case action
    normally; each secondary is deferred (`OUTREACH_COORDINATOR_DEFERRED`), never
    dropped (§4.4 / line 760)."""
    results: list[R.StepResult] = [R.execute_due_job(session, primary.job, now=now)]
    for sec in secondaries:
        R._write_action(
            session, sec.run, sec.case, action_type,
            outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
            block_reason=BlockReason.OUTREACH_COORDINATOR_DEFERRED, now=now,
        )
        offset = max(
            float(sec.node.get("timing_offset_hours", 0) or 0), _MERGE_DEFER_MIN_HOURS
        )
        sec.job.fire_at = timing.compute_fire_time(
            previous_completion=now,
            timing_offset_hours=offset,
            allowed_start=sec.rules.allowed_hours.start,
            allowed_end=sec.rules.allowed_hours.end,
            payday_adjustment=None,
        )
        session.flush()
        results.append(R.StepResult.DEFERRED)
    return results


__all__ = ["execute_merged", "merge_groups"]
