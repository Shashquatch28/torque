"""The runtime execution tick — Blueprint §5.1 workflow loop, driven by the
Postgres poller (§5.6) instead of Temporal (D-090).

`execute_due_job` runs ONE claimed `ScheduledJob` inside the caller's transaction
(the poller gives each job its own `session_scope`, so the whole tick — action +
budget + `active_step_id` + `CaseEvent`s + job row — commits or rolls back as one
unit, §2.3). The loop, per §5.1:

    resolve active_step_id → node
      → stopping-rule check (max_attempts / max_duration → EXHAUSTED)
      → allowed_hours re-check (DEFER: reschedule, never fire early)
      → guardrails (BLOCK → ACTION_BLOCKED + on_blocked edge;
                     DEFER → reschedule; AUTO_INSERT_PREDEBIT → §5.2.3 self-heal)
      → execute action (executor stub, §5.4) → ACTION_EXECUTED
      → STEP_TRANSITIONED (audit the graph move)
      → advance active_step_id + reschedule the timer, OR finalize at a terminal.

Idempotency & exactly-once: one pending job per run (`UNIQUE(run_id)`), claimed
`FOR UPDATE SKIP LOCKED`; a redelivered/duplicate poll finds no claimable row, and
a crash rolls the tick back leaving the timer for the next poll. `active_step_id`
is the single authoritative pointer (D-024) — never a parallel position system.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum, auto

from sqlalchemy import func
from sqlalchemy.orm import Session

from torque.compliance.pre_debit import PRE_DEBIT_MIN_GAP_HOURS
from torque.db.scoped import TenantScope
from torque.enums import (
    ActionOutcome,
    ActionType,
    Actor,
    BlockReason,
    CaseEventType,
    CaseStatus,
    MandateType,
    PlaybookRunStatus,
)
from torque.events import write_action_and_event
from torque.events.case_event_writer import append_case_event
from torque.execution import guardrails as G
from torque.execution import timing
from torque.execution.executor import ActionContext, channel_for, run_action
from torque.models import (
    Action,
    CardRetryBudget,
    Playbook,
    PlaybookRun,
    PreDebitNotification,
    RevenueLeakCase,
    ScheduledJob,
    UPIRetryBudget,
)
from torque.playbooks.stopping_rules import StoppingRules
from torque.policy import traversal
from torque.policy.engine import resolve_effective_stopping_rules

# Module 6 (`torque.coordination`) is imported LAZILY inside the functions that
# use it: `coordination` composes `torque.execution.*` predicates, so a
# module-level import here would be circular. By the time the runtime tick calls
# these, `torque.execution` is fully loaded. Same pattern as the lazy
# `state_machine` import in `_transition_case`.

_CONTACT_ACTIONS = frozenset(
    {
        ActionType.SEND_WHATSAPP,
        ActionType.SEND_EMAIL,
        ActionType.SEND_SMS,
        ActionType.GENERATE_PAYMENT_LINK,
        ActionType.SEND_PRE_DEBIT_NOTIFICATION,
    }
)
_NON_TERMINAL_RUN = (PlaybookRunStatus.RUNNING, PlaybookRunStatus.PAUSED)
_OUTCOME_TO_EDGE: dict[ActionOutcome, traversal.Outcome] = {
    ActionOutcome.SUCCESS: "on_success",
    ActionOutcome.FAILED: "on_failed",
    ActionOutcome.NO_RESPONSE: "on_no_response",
}


class StepResult(Enum):
    NOOP = auto()  # job's run is gone / already terminal
    EXECUTED = auto()  # an action fired and the run advanced
    BLOCKED = auto()  # guardrail blocked; followed on_blocked and advanced
    DEFERRED = auto()  # a *when* constraint; timer rescheduled, no action
    AUTO_INSERTED_PREDEBIT = auto()  # §5.2.3 self-heal; retry re-armed 24h out
    ESCALATED = auto()  # reached a human-escalation terminal
    ESCALATED_CEILING = auto()  # Module 6 §6.3: run tripped stopping_rules.escalation_ceiling
    MERGED = auto()  # Module 6 Part A §5: folded into a sibling case's merged Action
    EXHAUSTED = auto()  # ran out of attempts/duration or hit a non-escalate terminal
    ERROR = auto()  # the tick raised; its per-job SAVEPOINT was rolled back (F-2)


def execute_due_job(
    session: Session, job: ScheduledJob, *, now: datetime | None = None
) -> StepResult:
    now = now or datetime.now(UTC)
    scope = TenantScope(session, job.merchant_id)

    run = scope.get(PlaybookRun, job.run_id)
    if run is None or PlaybookRunStatus(run.status) not in _NON_TERMINAL_RUN:
        session.delete(job)  # stale timer for a finished/absent run
        session.flush()
        return StepResult.NOOP

    case = session.get(RevenueLeakCase, run.case_id)
    # Defence-in-depth (F-6): a run only ever exists for a canonical case (Module 4
    # activates non-superseded PLAYBOOK_ACTIVE cases, and §2.4 supersession is an
    # ingestion-time merge that precedes diagnosis/activation), so this is
    # unreachable in normal flow — but never execute a merged-away case. Drop the
    # timer and stop; no invented state transition.
    if case is None or case.superseded_by_case_id is not None:
        session.delete(job)
        session.flush()
        return StepResult.NOOP

    pinned = session.get(Playbook, (run.playbook_id, run.playbook_version))
    graph = pinned.steps_graph
    rules = resolve_effective_stopping_rules(session, run)
    step_id = run.active_step_id
    node = traversal.node(graph, step_id)
    action_type = ActionType(node["action_template"]["type"])

    # Module 6 §6.3 — escalation ceiling. "When do we give up on automation" is a
    # compliance/policy decision Module 6 owns, checked before the execution-layer
    # stopping bounds so an ESCALATED_TO_HUMAN outcome wins over EXHAUSTED. Trips
    # when accumulated unsuccessful attempts (blocked / failed / no-response,
    # Q-D) reach `stopping_rules.escalation_ceiling` (validated <= max_attempts).
    if _escalation_ceiling_hit(session, run, rules):
        return _escalate_on_ceiling(session, case, run, job, now=now)

    # Stopping rules (safety bounds; acyclic graphs usually terminate first).
    if _stopping_rule_hit(session, run, rules, now=now):
        return _finalize_exhausted(session, case, run, job)

    # allowed_hours re-check — a *when* constraint (§5.2.5): defer, never fire early.
    if not timing.within_allowed_hours(now, rules.allowed_hours.start, rules.allowed_hours.end):
        job.fire_at = timing.next_window_opening(
            now, rules.allowed_hours.start, rules.allowed_hours.end
        )
        session.flush()
        return StepResult.DEFERRED

    terminal = traversal.is_terminal(graph, step_id)

    # Guardrails (only for non-terminal actionable steps; the escalation terminal
    # and log-only actions carry none). Routed through the Module 6
    # `GuardrailEngine` facade (§6.2) — it composes the same §5.2 predicates plus
    # the Outreach Coordinator / WhatsApp gates and returns the same four-way
    # `GuardDecision` (D-097).
    if not terminal or action_type in _CONTACT_ACTIONS:
        decision = _guardrails(session, case, action_type, now=now, run=run, node=node)
        if decision.kind is G.GuardKind.DEFER:
            # A cross-leg-quiet-period / open-conversation defer (Part A §5) also
            # records an ACTION_BLOCKED / OUTREACH_COORDINATOR_DEFERRED row and
            # may flag the case for human pickup — the step is NOT advanced
            # (deferred, never skipped). A plain timing defer records nothing.
            if decision.block_reason is BlockReason.OUTREACH_COORDINATOR_DEFERRED:
                _write_action(
                    session, run, case, action_type,
                    outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
                    block_reason=BlockReason.OUTREACH_COORDINATOR_DEFERRED, now=now,
                )
            if decision.human_queue_reason is not None:
                from torque.coordination import human_queue

                human_queue.enqueue(
                    session, case=case, reason=decision.human_queue_reason, now=now
                )
            job.fire_at = decision.defer_until or _defer_target(action_type, rules, now=now)
            session.flush()
            return StepResult.DEFERRED
        if decision.kind is G.GuardKind.AUTO_INSERT_PREDEBIT:
            return _auto_insert_predebit(
                session, case, run, job, attempt=decision.predebit_attempt_number, now=now
            )
        if decision.kind is G.GuardKind.BLOCK:
            _write_action(
                session, run, case, action_type,
                outcome=ActionOutcome.BLOCKED_BY_GUARDRAIL,
                block_reason=decision.block_reason, now=now,
            )
            return _advance(session, case, run, job, graph, step_id, "on_blocked",
                            ActionOutcome.BLOCKED_BY_GUARDRAIL, now=now)

    # Execute the action (stub, §5.4).
    channel = channel_for(action_type)
    outcome = run_action(
        ActionContext(
            action_type=action_type,
            channel=channel,
            template=(node.get("params") or {}).get("template"),
        )
    )
    _write_action(session, run, case, action_type, outcome=outcome, block_reason=None, now=now)
    if action_type is ActionType.RETRY_PAYMENT:
        _consume_retry_budget(session, case)
    elif action_type is ActionType.SEND_PRE_DEBIT_NOTIFICATION:
        # A graph pre-debit node records its compliance row (covering the next
        # retry attempt) — the same row the §5.2.3 auto-insert would create.
        _write_predebit_row(
            session, case, attempt=G.executed_retry_count(session, case) + 1, now=now
        )

    if terminal:
        return _finalize_terminal(session, case, run, job, step_id, action_type, outcome)

    edge = _OUTCOME_TO_EDGE.get(outcome, "on_no_response")
    return _advance(session, case, run, job, graph, step_id, edge, outcome, now=now)


# --- advancement + finalization ----------------------------------------------


def _advance(
    session: Session,
    case: RevenueLeakCase,
    run: PlaybookRun,
    job: ScheduledJob,
    graph: dict,
    from_step: str,
    edge: traversal.Outcome,
    outcome: ActionOutcome,
    *,
    now: datetime,
) -> StepResult:
    next_id = traversal.next_step_id(graph, from_step, edge)
    blocked = outcome is ActionOutcome.BLOCKED_BY_GUARDRAIL
    result = StepResult.BLOCKED if blocked else StepResult.EXECUTED

    if next_id is None:  # no edge for this outcome → the ladder ends here
        _step_event(session, case, run, from_step, None, None, outcome)
        return _finalize_exhausted(session, case, run, job)

    _step_event(session, case, run, from_step, next_id, edge, outcome)
    run.active_step_id = next_id
    next_node = traversal.node(graph, next_id)
    job.fire_at = _next_fire_time(session, case, run, next_node, now=now)
    session.flush()
    return result


def _finalize_terminal(
    session: Session,
    case: RevenueLeakCase,
    run: PlaybookRun,
    job: ScheduledJob,
    step_id: str,
    action_type: ActionType,
    outcome: ActionOutcome,
) -> StepResult:
    _step_event(session, case, run, step_id, None, None, outcome)
    if action_type is ActionType.ESCALATE_HUMAN:
        _transition_case(session, case, CaseStatus.ESCALATED_TO_HUMAN, "playbook_escalation")
        run.status = PlaybookRunStatus.ESCALATED
        session.delete(job)
        session.flush()
        return StepResult.ESCALATED
    return _finalize_exhausted(session, case, run, job)


def _finalize_exhausted(
    session: Session, case: RevenueLeakCase, run: PlaybookRun, job: ScheduledJob
) -> StepResult:
    """The playbook ran its course without recovery. The run completes; the case
    is EXHAUSTED (recovery, if it happens, is Module 7's out-of-band closure)."""
    if CaseStatus(case.status) is CaseStatus.PLAYBOOK_ACTIVE:
        _transition_case(session, case, CaseStatus.EXHAUSTED, "playbook_exhausted")
    run.status = PlaybookRunStatus.COMPLETED
    session.delete(job)
    session.flush()
    return StepResult.EXHAUSTED


# --- Module 6 §6.3 — escalation ceiling ------------------------------------


def _escalation_ceiling_hit(session: Session, run: PlaybookRun, rules: StoppingRules) -> bool:
    """True once the run's accumulated unsuccessful attempts (blocked / failed /
    no-response Actions — Q-D) reach `stopping_rules.escalation_ceiling`. The
    ceiling is validated `<= max_attempts` at playbook-save time, so it is always
    a reachable sub-bound on the attempt cap."""
    from torque.coordination.outreach_coordinator import unsuccessful_action_count

    hit = unsuccessful_action_count(
        session, merchant_id=run.merchant_id, run_id=run.run_id
    )
    return hit >= rules.escalation_ceiling


def _escalate_on_ceiling(
    session: Session,
    case: RevenueLeakCase,
    run: PlaybookRun,
    job: ScheduledJob,
    *,
    now: datetime,
) -> StepResult:
    """Module 6 (not Module 5) transitions the case to `ESCALATED_TO_HUMAN`, sets
    the run `ESCALATED`, enqueues the case for human pickup, and drops the timer —
    one transition only, and never in addition to a graph-terminal `ESCALATE_HUMAN`
    (this check short-circuits the tick before that node ever executes)."""
    from torque.coordination import human_queue

    _transition_case(session, case, CaseStatus.ESCALATED_TO_HUMAN, "escalation_ceiling")
    run.status = PlaybookRunStatus.ESCALATED
    human_queue.enqueue(
        session,
        case=case,
        reason=human_queue.HumanQueueReason.ESCALATION_CEILING,
        now=now,
    )
    session.delete(job)
    session.flush()
    return StepResult.ESCALATED_CEILING


# --- pre-debit self-heal (§5.2.3) --------------------------------------------


def _auto_insert_predebit(
    session: Session,
    case: RevenueLeakCase,
    run: PlaybookRun,
    job: ScheduledJob,
    *,
    attempt: int,
    now: datetime,
) -> StepResult:
    """Send the pre-debit notice now and re-arm the *same* retry step 24h out,
    instead of dead-ending on `PRE_DEBIT_GAP_NOT_MET` — the graph position does not
    move (the notice sits *ahead of* the retry, §5.2.3)."""
    _write_action(
        session, run, case, ActionType.SEND_PRE_DEBIT_NOTIFICATION,
        outcome=ActionOutcome.SUCCESS, block_reason=None, now=now,
    )
    _write_predebit_row(session, case, attempt=attempt, now=now)
    job.fire_at = now + timedelta(hours=PRE_DEBIT_MIN_GAP_HOURS)
    session.flush()
    return StepResult.AUTO_INSERTED_PREDEBIT


def _write_predebit_row(
    session: Session, case: RevenueLeakCase, *, attempt: int, now: datetime
) -> None:
    TenantScope(session, case.merchant_id).add(
        PreDebitNotification(
            case_id=case.case_id,
            notified_at=now,
            covers_attempt_number=attempt,
            channel=channel_for(ActionType.SEND_PRE_DEBIT_NOTIFICATION) or "whatsapp",
            notified_amount=case.amount_at_risk,
        )
    )
    session.flush()


# --- helpers -----------------------------------------------------------------


def _guardrails(
    session: Session,
    case: RevenueLeakCase,
    action_type: ActionType,
    *,
    now: datetime,
    run: PlaybookRun,
    node: dict,
):
    """Consult the Module 6 `GuardrailEngine` facade (§6.2). It runs the §5.2
    sequence — the Module 5 retry/systemic/pre-debit predicates unchanged, plus
    the Outreach Coordinator cross-leg quiet period, the WhatsApp consent +
    template gate, and the open-conversation suspension — and returns the same
    four-way `GuardDecision` the runner already handles (D-097)."""
    from torque.coordination.guardrail_engine import GuardrailEngine

    return GuardrailEngine.check(
        session,
        action_type=action_type,
        case=case,
        now=now,
        run=run,
        node=node,
        params=(node.get("params") or {}),
    )


def _defer_target(action_type: ActionType, rules: StoppingRules, *, now: datetime) -> datetime:
    # A UPI execution-window defer waits past the NPCI peak; anything else waits
    # for the next contact window.
    upi = timing.next_upi_execution_time(now)
    if upi > now:
        return upi
    return timing.next_window_opening(now, rules.allowed_hours.start, rules.allowed_hours.end)


def _next_fire_time(
    session: Session, case: RevenueLeakCase, run: PlaybookRun, next_node: dict, *, now: datetime
) -> datetime:
    # The §4.3 payday substitution applies to "the next node" — the FIRST action
    # scheduled after diagnosis (the entry step, armed by `schedule_run`), NOT to
    # every subsequent step (that would push each rung a further month out — the
    # nudge/escalate would each jump to the next month-end). Advancing steps use
    # their static graph offsets from the previous step's completion (D-094).
    rules = resolve_effective_stopping_rules(session, run)
    return timing.compute_fire_time(
        previous_completion=now,
        timing_offset_hours=float(next_node.get("timing_offset_hours", 0)),
        allowed_start=rules.allowed_hours.start,
        allowed_end=rules.allowed_hours.end,
        payday_adjustment=None,
    )


def _stopping_rule_hit(
    session: Session,
    run: PlaybookRun,
    rules: StoppingRules,
    *,
    now: datetime,
) -> bool:
    """`max_duration_days` bounds the run's *active execution span* — measured from
    its FIRST executed action, not from `PlaybookRun.created_at` (D-094). A
    deliberately-scheduled wait before the first action (a long `timing_offset`, or
    a §4.3 payday-cycle target that can sit ~a month out) is a timing delay, not
    duration spent (§4.2/§4.3, D-025): a run must not exhaust merely because policy
    scheduled its first action on the next payday. `Action.executed_at` is stamped
    with the execution clock, so this reads consistently in tests and production.
    `max_attempts` counts executed (non-blocked) actions."""
    scope = TenantScope(session, run.merchant_id)
    first_executed = session.scalar(
        scope.select(Action)
        .where(Action.run_id == run.run_id)
        .where(Action.executed_at.is_not(None))
        .with_only_columns(func.min(Action.executed_at))
    )
    if first_executed is not None:
        started = first_executed if first_executed.tzinfo else first_executed.replace(tzinfo=UTC)
        if now - started > timedelta(days=rules.max_duration_days):
            return True
    executed = int(
        session.scalar(
            scope.select(Action)
            .where(Action.run_id == run.run_id)
            .where(Action.outcome != ActionOutcome.BLOCKED_BY_GUARDRAIL)
            .with_only_columns(func.count())
        )
        or 0
    )
    return executed >= rules.max_attempts


def _write_action(
    session: Session,
    run: PlaybookRun,
    case: RevenueLeakCase,
    action_type: ActionType,
    *,
    outcome: ActionOutcome,
    block_reason: BlockReason | None,
    now: datetime,
) -> Action:
    blocked = outcome is ActionOutcome.BLOCKED_BY_GUARDRAIL
    action = Action(
        merchant_id=case.merchant_id,
        primary_case_id=case.case_id,
        run_id=run.run_id,
        action_type=action_type,
        channel=channel_for(action_type),
        executed_at=None if blocked else now,
        outcome=outcome,
        block_reason=block_reason,
        cost=None,
    )
    return write_action_and_event(
        session, action=action, actor=Actor.AGENT, counterparty_id=case.counterparty_id
    )


def _step_event(
    session: Session,
    case: RevenueLeakCase,
    run: PlaybookRun,
    from_step: str,
    to_step: str | None,
    edge_condition: str | None,
    outcome: ActionOutcome,
) -> None:
    append_case_event(
        session,
        case_id=case.case_id,
        event_type=CaseEventType.STEP_TRANSITIONED,
        payload={
            "run_id": str(run.run_id),
            "from_step_id": from_step,
            "to_step_id": to_step,
            "edge_condition": edge_condition,
            "outcome": ActionOutcome(outcome).value,
        },
        actor=Actor.AGENT,
        counterparty_id=case.counterparty_id,
    )


def _transition_case(
    session: Session, case: RevenueLeakCase, target: CaseStatus, trigger: str
) -> None:
    from torque.state_machine import transition_case

    transition_case(session, case, target, trigger=trigger, actor=Actor.AGENT)


def _consume_retry_budget(session: Session, case: RevenueLeakCase) -> None:
    """Increment the rail counter for a card/UPI retry that actually fired, in the
    same transaction as the Action write. NACH re-presentment consumes no counter
    here — dishonour counts advance only on a bank return file (external, D-072).
    Card/UPI rows are row-locked for the update so a concurrent tick cannot
    double-count (item 12)."""
    scope = TenantScope(session, case.merchant_id)
    mandate_type = G._mandate_type_of(case)
    mandate_id = (case.context or {}).get("mandate_id") or ""

    if mandate_type is MandateType.UPI_AUTOPAY:
        budget = session.scalars(
            scope.select(UPIRetryBudget)
            .where(UPIRetryBudget.mandate_id == mandate_id)
            .with_for_update()
        ).first()
        if budget is not None:
            budget.attempts_used += 1
            session.flush()
        return
    if mandate_type is MandateType.NACH:
        return
    # CARD (payment leg, or subscription card).
    token = G._card_token_hash(session, case)
    if not token:
        return
    budget = session.scalars(
        scope.select(CardRetryBudget)
        .where(CardRetryBudget.card_token_hash == token)
        .with_for_update()
    ).first()
    if budget is not None:
        budget.attempts_used_24h += 1
        budget.attempts_used_30d += 1
        session.flush()
