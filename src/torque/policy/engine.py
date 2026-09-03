"""The Policy & Playbook Engine orchestrator — Blueprint §4.

`activate_case` takes a diagnosed, `PLAYBOOK_ACTIVE` case (Module 3 routed it
there when `diagnosis_confidence >= T`), selects the eligible catalog playbook,
resolves merchant availability, and instantiates a **version-pinned**
`PlaybookRun` positioned at the graph's entry step. Its contract ends there: the
run + "the rules for reading its graph" (`torque.policy.traversal`) are what
Module 5 needs to execute. Module 4 fires no actions, advances no `active_step_id`,
computes no fire times, and builds no Temporal workflow.

    DIAGNOSING ──(≥T, Module 3)──▶ PLAYBOOK_ACTIVE ──(Module 4)──▶ PlaybookRun(RUNNING)
                                                   └─(no playbook / disabled)─▶ ESCALATED_TO_HUMAN

**Eligibility / idempotency.** Only a `PLAYBOOK_ACTIVE`, non-superseded case is
activated; any other state — and a case that already has a live (`RUNNING` /
`PAUSED`) run — is a no-op. A case whose `root_cause_code` has no catalog playbook
(the "trivial" §4.1 causes) or whose merchant has disabled that playbook is routed
to `ESCALATED_TO_HUMAN` via the existing legal edge (D-086) — never left stuck in
`PLAYBOOK_ACTIVE`, never given an invented state.

**Version pinning (D-021/D-024).** The run pins `(playbook_id, playbook_version)`
to the latest catalog version at creation; a later version never alters it.

**Boundary with Module 5/6.** Stopping rules resolved here are *what the policy
says* (`resolve_effective_stopping_rules`); *whether an action is actually
permitted* (retry budgets, quiet hours, guardrails) is Module 5/6. Timing
*computation* is Module 5 (D-025); Module 4 owns only the payday *policy* gate
(`torque.policy.payday`).
"""

from __future__ import annotations

import uuid
from enum import Enum, auto

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.enums import Actor, CaseStatus, LegType, MandateType, PlaybookRunStatus
from torque.events.case_event_writer import atomic
from torque.exceptions import PlaybookNotFoundError
from torque.models import (
    MerchantPlaybookConfig,
    Playbook,
    PlaybookRun,
    RevenueLeakCase,
)
from torque.playbooks.resolution import effective_stopping_rules
from torque.playbooks.stopping_rules import StoppingRules
from torque.policy.selection import select_playbook_id
from torque.policy.traversal import entry_step_id
from torque.state_machine import transition_case

_NON_TERMINAL_RUN = (PlaybookRunStatus.RUNNING, PlaybookRunStatus.PAUSED)
_ESCALATE_NO_PLAYBOOK = "no_automated_playbook_for_root_cause"
_ESCALATE_DISABLED = "merchant_disabled_playbook"


class ActivationOutcome(Enum):
    """The outcome of one `activate_case` call."""

    #: Not eligible — wrong state, superseded, missing, or a live run already
    #: exists (idempotent under redelivery).
    NOOP = auto()
    #: A version-pinned `PlaybookRun` was created (case stays `PLAYBOOK_ACTIVE`).
    RUN_CREATED = auto()
    #: No catalog playbook for the root cause → `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN`.
    ESCALATED_NO_PLAYBOOK = auto()
    #: Merchant disabled this playbook → `PLAYBOOK_ACTIVE → ESCALATED_TO_HUMAN`.
    ESCALATED_DISABLED = auto()


def _mandate_type(case: RevenueLeakCase) -> MandateType | None:
    if LegType(case.leg_type) is not LegType.SUBSCRIPTION_FAILURE:
        return None
    raw = (case.context or {}).get("mandate_type")
    return MandateType(raw) if raw else None


def _live_run(session: Session, case: RevenueLeakCase) -> PlaybookRun | None:
    return session.scalars(
        TenantScope(session, case.merchant_id)
        .select(PlaybookRun)
        .where(PlaybookRun.case_id == case.case_id)
        .where(PlaybookRun.status.in_(_NON_TERMINAL_RUN))
    ).first()


def _latest_version(session: Session, playbook_id: str) -> int | None:
    return session.scalar(
        select(func.max(Playbook.version)).where(Playbook.playbook_id == playbook_id)
    )


def _merchant_config(
    session: Session, *, merchant_id: str, playbook_id: str
) -> MerchantPlaybookConfig | None:
    return session.scalars(
        TenantScope(session, merchant_id)
        .select(MerchantPlaybookConfig)
        .where(MerchantPlaybookConfig.playbook_id == playbook_id)
    ).first()


def _escalate(
    session: Session, case: RevenueLeakCase, *, trigger: str, reason: str
) -> None:
    transition_case(
        session,
        case,
        CaseStatus.ESCALATED_TO_HUMAN,
        trigger=trigger,
        actor=Actor.AGENT,
        reasoning=reason,
    )
    session.flush()


def activate_case(session: Session, *, case_id: uuid.UUID) -> ActivationOutcome:
    """Select a playbook for one `PLAYBOOK_ACTIVE` case and instantiate its run
    (or escalate). Idempotent; the caller owns the transaction. All writes are one
    atomic unit."""
    case = session.get(RevenueLeakCase, case_id)
    if case is None:
        return ActivationOutcome.NOOP
    if (
        CaseStatus(case.status) is not CaseStatus.PLAYBOOK_ACTIVE
        or case.superseded_by_case_id is not None
    ):
        return ActivationOutcome.NOOP
    if _live_run(session, case) is not None:
        return ActivationOutcome.NOOP  # a run already drives this case

    playbook_id = select_playbook_id(
        leg_type=case.leg_type,
        root_cause_code=case.root_cause_code or "",
        mandate_type=_mandate_type(case),
    )

    with atomic(session):
        if playbook_id is None:
            _escalate(
                session,
                case,
                trigger=_ESCALATE_NO_PLAYBOOK,
                reason=(
                    f"No automated playbook for root_cause_code={case.root_cause_code!r} "
                    f"(leg {case.leg_type}); routing to human review (§4.1)."
                ),
            )
            return ActivationOutcome.ESCALATED_NO_PLAYBOOK

        config = _merchant_config(
            session, merchant_id=case.merchant_id, playbook_id=playbook_id
        )
        if config is not None and not config.enabled:
            _escalate(
                session,
                case,
                trigger=_ESCALATE_DISABLED,
                reason=(
                    f"Merchant has disabled {playbook_id}; routing to human review "
                    f"(§4.2 enabled flag)."
                ),
            )
            return ActivationOutcome.ESCALATED_DISABLED

        version = _latest_version(session, playbook_id)
        if version is None:
            raise PlaybookNotFoundError(
                f"catalog playbook {playbook_id!r} has no published version — "
                f"seed the catalog (torque.policy.catalog.seed_catalog) first"
            )
        pinned = session.get(Playbook, (playbook_id, version))

        run = PlaybookRun(
            case_id=case.case_id,
            playbook_id=playbook_id,
            playbook_version=version,
            active_step_id=entry_step_id(pinned.steps_graph),
            status=PlaybookRunStatus.RUNNING,
        )
        TenantScope(session, case.merchant_id).add(run)
        session.flush()
        return ActivationOutcome.RUN_CREATED


def resolve_effective_stopping_rules(session: Session, run: PlaybookRun) -> StoppingRules:
    """The stopping rules a run actually uses: the merchant's partial override
    (if any) deep-merged onto the run's **pinned** playbook version's base rules,
    then fully validated (Blueprint §4.2 / D-023). Reflects the current merchant
    override — `enabled` gates availability at creation, not rule resolution.

    This is *what the policy says*; whether an action is permitted (budgets, quiet
    hours, guardrails) is Module 5/6.
    """
    pinned = session.get(Playbook, (run.playbook_id, run.playbook_version))
    if pinned is None:  # pragma: no cover - composite FK guarantees the row exists
        raise PlaybookNotFoundError(
            f"run {run.run_id} pins {run.playbook_id!r} v{run.playbook_version}, "
            f"which is missing"
        )
    config = _merchant_config(
        session, merchant_id=run.merchant_id, playbook_id=run.playbook_id
    )
    override = config.stopping_rules_override if config is not None else None
    return effective_stopping_rules(pinned.stopping_rules, override)
