"""`RevenueLeakCase.status` state machine — Blueprint v7 Section 4 + Part C.

The transition set is transcribed from the Section 4 diagram, plus:
* Part C item 1: `DIAGNOSING -> ESCALATED_TO_HUMAN` (direct, bypassing
  `PLAYBOOK_ACTIVE`, for `diagnosis_confidence < T`).
* Confirmed R4 addition: `PARTIALLY_RECOVERED -> PLAYBOOK_ACTIVE` is legal ONLY
  for `leg_type = B2B_RECEIVABLE` (partial payment against a bundled invoice
  thread; the case keeps dunning the remainder). For the other three legs
  `PARTIALLY_RECOVERED` is terminal.

Also here: `apply_network_directive` (the only sanctioned writer of
`network_directive_tier`, enforcing most-restrictive-wins) and
`sync_control_group` (keeps the denormalised `control_group` in step with the
cohort assignment).

`PLAYBOOK_ACTIVE -> SYSTEMIC_HOLD` was ADDED in Milestone 7c (U-01 #3, approved):
Module 2 §2.5's outage sweep may catch an already-active case. It is a legal but
DORMANT edge — M7c's systemic-detection job only sweeps `DETECTED` cases, and no
case reaches `PLAYBOOK_ACTIVE` until Module 5 exists. Resume is the existing
`SYSTEMIC_HOLD -> DIAGNOSING` (§3: "re-queued for diagnosis in a batch"); there is
deliberately NO `SYSTEMIC_HOLD -> PLAYBOOK_ACTIVE` restoration edge.

NOT YET ADDED — flagged, pending confirmation before the owning module is built:
* `DETECTED -> CANCELLED`, `DIAGNOSING -> CANCELLED` — required by Module 7
  §7.1.4 (payment arrives before diagnosis finishes). Not in the Section 4
  diagram.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.enums import Actor, CaseEventType, CaseStatus, LegType, MacTier
from torque.events.case_event_writer import append_case_event
from torque.exceptions import IllegalTransitionError, MonotonicityViolation
from torque.models.guards import network_directive_writer, tier_rank
from torque.models.merchant_counterparty import MerchantCounterparty
from torque.models.revenue_leak_case import RevenueLeakCase

# Base transitions from the Section 4 diagram (+ Part C item 1).
_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.DETECTED: {CaseStatus.SYSTEMIC_HOLD, CaseStatus.DIAGNOSING},
    CaseStatus.SYSTEMIC_HOLD: {CaseStatus.DIAGNOSING},
    CaseStatus.DIAGNOSING: {CaseStatus.PLAYBOOK_ACTIVE, CaseStatus.ESCALATED_TO_HUMAN},
    CaseStatus.PLAYBOOK_ACTIVE: {
        CaseStatus.RECOVERED,
        CaseStatus.PARTIALLY_RECOVERED,
        CaseStatus.EXHAUSTED,
        CaseStatus.ESCALATED_TO_HUMAN,
        CaseStatus.PAUSED,
        CaseStatus.CANCELLED,
        CaseStatus.SYSTEMIC_HOLD,  # U-01 #3 — approved M7c; dormant until Module 5
    },
    CaseStatus.PAUSED: {CaseStatus.PLAYBOOK_ACTIVE},
    CaseStatus.ESCALATED_TO_HUMAN: {
        CaseStatus.RECOVERED,
        CaseStatus.PARTIALLY_RECOVERED,
        CaseStatus.WRITTEN_OFF,
    },
    # PARTIALLY_RECOVERED handled specially (leg-dependent) in `allowed_targets`.
    CaseStatus.PARTIALLY_RECOVERED: set(),
    CaseStatus.RECOVERED: set(),
    CaseStatus.EXHAUSTED: set(),
    CaseStatus.CANCELLED: set(),
    CaseStatus.WRITTEN_OFF: set(),
}

TERMINAL_STATUSES: frozenset[CaseStatus] = frozenset(
    {
        CaseStatus.RECOVERED,
        CaseStatus.EXHAUSTED,
        CaseStatus.CANCELLED,
        CaseStatus.WRITTEN_OFF,
        # PARTIALLY_RECOVERED is terminal for every leg EXCEPT B2B_RECEIVABLE.
    }
)


def allowed_targets(current: CaseStatus, leg_type: LegType) -> set[CaseStatus]:
    targets = set(_TRANSITIONS[CaseStatus(current)])
    if (
        CaseStatus(current) is CaseStatus.PARTIALLY_RECOVERED
        and LegType(leg_type) is LegType.B2B_RECEIVABLE
    ):
        targets.add(CaseStatus.PLAYBOOK_ACTIVE)
    return targets


def is_terminal(status: CaseStatus, leg_type: LegType) -> bool:
    if CaseStatus(status) is CaseStatus.PARTIALLY_RECOVERED:
        return LegType(leg_type) is not LegType.B2B_RECEIVABLE
    return CaseStatus(status) in TERMINAL_STATUSES


def assert_transition(
    current: CaseStatus, target: CaseStatus, leg_type: LegType
) -> None:
    if CaseStatus(target) not in allowed_targets(current, leg_type):
        raise IllegalTransitionError(
            f"{current} -> {target} is not a legal transition for leg_type "
            f"{leg_type} (Blueprint Section 4 + Part C)"
        )


def transition_case(
    session: Session,
    case: RevenueLeakCase,
    target: CaseStatus,
    *,
    trigger: str,
    actor: Actor = Actor.SYSTEM,
    reasoning: str | None = None,
) -> None:
    """Validate and apply a status change, writing the `STATUS_CHANGED`
    `CaseEvent` on the same session (caller controls the transaction)."""
    current = CaseStatus(case.status)
    assert_transition(current, target, case.leg_type)
    append_case_event(
        session,
        case_id=case.case_id,
        event_type=CaseEventType.STATUS_CHANGED,
        payload={
            "from_status": current.value,
            "to_status": CaseStatus(target).value,
            "trigger": trigger,
        },
        actor=actor,
        reasoning=reasoning,
        counterparty_id=case.counterparty_id,
    )
    case.status = CaseStatus(target)


def apply_network_directive(
    session: Session,
    case: RevenueLeakCase,
    *,
    mac_code: str,
    tier: MacTier,
) -> None:
    """The ONLY sanctioned writer of `network_directive_tier`.

    Enforces most-restrictive-wins: the tier never downgrades
    (`TIER_1 > TIER_3 > TIER_2 > TIMED_RETRY > null`). Re-applying an equal or
    more restrictive tier is fine; a less restrictive one raises.

    The case must already be attached to `session`.
    """
    tier = MacTier(tier)
    current = case.network_directive_tier
    if tier_rank(tier) < tier_rank(current):
        raise MonotonicityViolation(
            f"network_directive downgrade {current} -> {tier} rejected"
        )
    with network_directive_writer(session):
        case.network_directive_mac_code = mac_code
        case.network_directive_tier = tier
        session.flush()


def sync_control_group(session: Session, case: RevenueLeakCase) -> None:
    """Refresh the denormalised `control_group` from the counterparty's cohort
    assignment for this merchant. No-op if the cohort is unassigned."""
    mc = session.scalars(
        select(MerchantCounterparty)
        .where(MerchantCounterparty.merchant_id == case.merchant_id)
        .where(MerchantCounterparty.counterparty_id == case.counterparty_id)
    ).first()
    if mc is not None and mc.in_control_cohort is not None:
        case.control_group = mc.in_control_cohort
