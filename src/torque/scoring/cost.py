"""Forward-looking intervention cost — Blueprint Module 8 §8.2.

`cost` for a case = the sum of `ChannelRateCard.rate_per_unit` for the channel(s)
the assigned playbook's **next likely step** would use. This is the *expected
cost of the next intervention*, explicitly **not**:

* historical outreach spend,
* the cost of a previous `Action`,
* an arbitrary constant,
* the old Module 6 `priority()` placeholder.

**Resolving "the next likely step" (D-111):**

1. A live `PlaybookRun` (`RUNNING`) for the case, positioned at `active_step_id`
   — that node *is* the next intervention (`runner.execute_due_job` reads
   `active_step_id`, executes it, then advances). `next_step_source = LIVE_RUN`.
2. No live run yet, but the case is diagnosed (`root_cause_code` set) — resolve
   the *candidate* playbook via `torque.policy.selection.select_playbook_id` and
   take its entry node. `next_step_source = CANDIDATE_PLAYBOOK`. (Module 4's
   run-instantiation is not always wired at scoring time — D-093 — so this keeps
   the cost meaningful the moment diagnosis completes.)
3. Neither (e.g. a brand-new `DETECTED` case at creation time) —
   `next_step_source = NONE`.

**Channels:** `torque.execution.executor.channel_for(action_type)` maps the next
node's action type to its rate-card channel string. `RETRY_PAYMENT`,
`ESCALATE_HUMAN`, `LOG_PROMISE`, `SYSTEMIC_HOLD` carry no messaging channel;
`GENERATE_PAYMENT_LINK` maps to `"payment_link"`, which is not a seeded
`ChannelRateCard` row. Rates are looked up per channel and summed as `Decimal`.

**Zero / missing / unpriced cost — the conservative choice (D-111).** The
blueprint does not specify what to do when the forward cost is zero or
unavailable. A missing cost is an *absence of information*, not evidence of a
free intervention, and `(probability × amount) ÷ 0` is undefined. So the divisor
**floors** at `PolicyConfig.recovery_score_cost_floor` (default ₹0.01 — one
paisa, ≈ the cheapest real channel). `effective_cost` is the divisor;
`floor_applied` says whether the floor bit; `cost_basis` records the provenance:

* `PRICED`                 — a real `ChannelRateCard` rate drove the cost (its
  sum may still be ≥ the floor, or below it — e.g. a rate of 0 — in which case
  `floor_applied` is true but the basis stays honest that a rate was found).
* `FLOOR_NO_CHANNEL`       — the next step has no messaging channel (a retry) →
  no rate-card lookup possible; the divisor is the floor.
* `FLOOR_UNPRICED_CHANNEL` — a channel resolved but has no `ChannelRateCard` row
  (e.g. `"payment_link"`) → the rate is unknown; the divisor is the floor.
* `FLOOR_NO_PLAYBOOK`      — no live run and no candidate playbook (a brand-new
  `DETECTED` case, pre-diagnosis) → no next step to price.

A genuinely free next step (a retry) still ranks highest — just finitely — which
is the correct resource-aware prioritisation. Negative rates are impossible
(`ck_channel_rate_card_rate_per_unit_non_negative`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torque.config import get_policy
from torque.db.scoped import TenantScope
from torque.enums import ActionType, LegType, MandateType, PlaybookRunStatus
from torque.execution.executor import channel_for
from torque.models import ChannelRateCard, Playbook, PlaybookRun, RevenueLeakCase
from torque.policy.selection import select_playbook_id
from torque.policy.traversal import entry_step_id
from torque.policy.traversal import node as graph_node

_ZERO = Decimal("0")
_COST_QUANT = Decimal("0.0001")


class NextStepSource(StrEnum):
    LIVE_RUN = "LIVE_RUN"
    CANDIDATE_PLAYBOOK = "CANDIDATE_PLAYBOOK"
    NONE = "NONE"


class CostBasis(StrEnum):
    PRICED = "PRICED"
    FLOOR_NO_CHANNEL = "FLOOR_NO_CHANNEL"
    FLOOR_UNPRICED_CHANNEL = "FLOOR_UNPRICED_CHANNEL"
    FLOOR_NO_PLAYBOOK = "FLOOR_NO_PLAYBOOK"


@dataclass(frozen=True)
class CostBreakdown:
    """The forward intervention cost for one case, with its provenance."""

    raw_cost: Decimal
    effective_cost: Decimal
    floor: Decimal
    floor_applied: bool
    cost_basis: CostBasis
    next_step_source: NextStepSource
    next_step_action_type: str | None
    channels: tuple[str, ...] = field(default_factory=tuple)
    unpriced_channels: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "raw_cost": str(self.raw_cost),
            "effective_cost": str(self.effective_cost),
            "floor": str(self.floor),
            "floor_applied": self.floor_applied,
            "cost_basis": self.cost_basis.value,
            "next_step_source": self.next_step_source.value,
            "next_step_action_type": self.next_step_action_type,
            "channels": list(self.channels),
            "unpriced_channels": list(self.unpriced_channels),
        }


def _cost_floor() -> Decimal:
    return Decimal(str(get_policy().recovery_score_cost_floor))


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
        .where(PlaybookRun.status == PlaybookRunStatus.RUNNING)
        .order_by(PlaybookRun.created_at.desc())
    ).first()


def _latest_version(session: Session, playbook_id: str) -> int | None:
    return session.scalar(
        select(func.max(Playbook.version)).where(Playbook.playbook_id == playbook_id)
    )


def _next_node(session: Session, case: RevenueLeakCase) -> tuple[dict | None, NextStepSource]:
    """The graph node for the case's next likely intervention, plus its source."""
    run = _live_run(session, case)
    if run is not None and run.active_step_id:
        pinned = session.get(Playbook, (run.playbook_id, run.playbook_version))
        if pinned is not None:
            try:
                return graph_node(pinned.steps_graph, run.active_step_id), NextStepSource.LIVE_RUN
            except Exception:  # noqa: BLE001 — a malformed pointer falls through to candidate
                pass

    if case.root_cause_code:
        playbook_id = select_playbook_id(
            leg_type=case.leg_type,
            root_cause_code=case.root_cause_code,
            mandate_type=_mandate_type(case),
        )
        if playbook_id is not None:
            version = _latest_version(session, playbook_id)
            if version is not None:
                pinned = session.get(Playbook, (playbook_id, version))
                if pinned is not None:
                    entry = entry_step_id(pinned.steps_graph)
                    return graph_node(pinned.steps_graph, entry), NextStepSource.CANDIDATE_PLAYBOOK

    return None, NextStepSource.NONE


def _rate_for(session: Session, channel: str) -> Decimal | None:
    row = session.get(ChannelRateCard, channel)
    return Decimal(str(row.rate_per_unit)) if row is not None else None


def compute_cost(session: Session, case: RevenueLeakCase) -> CostBreakdown:
    """The forward intervention cost for `case` (§8.2 / D-111)."""
    floor = _cost_floor()
    node, source = _next_node(session, case)

    if node is None:
        return CostBreakdown(
            raw_cost=_ZERO,
            effective_cost=floor,
            floor=floor,
            floor_applied=True,
            cost_basis=CostBasis.FLOOR_NO_PLAYBOOK,
            next_step_source=source,
            next_step_action_type=None,
        )

    action_type = str(node["action_template"]["type"])
    channel = channel_for(ActionType(action_type))
    channels = (channel,) if channel else ()

    if not channels:
        return CostBreakdown(
            raw_cost=_ZERO,
            effective_cost=floor,
            floor=floor,
            floor_applied=True,
            cost_basis=CostBasis.FLOOR_NO_CHANNEL,
            next_step_source=source,
            next_step_action_type=action_type,
        )

    raw = _ZERO
    unpriced: list[str] = []
    for ch in channels:
        rate = _rate_for(session, ch)
        if rate is None:
            unpriced.append(ch)
        else:
            raw += rate
    raw = raw.quantize(_COST_QUANT)

    if raw >= floor:
        return CostBreakdown(
            raw_cost=raw,
            effective_cost=raw,
            floor=floor,
            floor_applied=False,
            cost_basis=CostBasis.PRICED,
            next_step_source=source,
            next_step_action_type=action_type,
            channels=channels,
            unpriced_channels=tuple(unpriced),
        )

    # raw_cost < floor with a channel that DOES resolve: either the channel has
    # no rate-card row (unpriced), or it is priced but genuinely below the floor
    # (e.g. a rate of 0). The first is an information gap; the second is a real,
    # tiny rate. Either way the divisor floors — but the basis is honest.
    basis = CostBasis.FLOOR_UNPRICED_CHANNEL if unpriced else CostBasis.PRICED
    return CostBreakdown(
        raw_cost=raw,
        effective_cost=floor,
        floor=floor,
        floor_applied=True,
        cost_basis=basis,
        next_step_source=source,
        next_step_action_type=action_type,
        channels=channels,
        unpriced_channels=tuple(unpriced),
    )


__all__ = ["CostBasis", "CostBreakdown", "NextStepSource", "compute_cost"]
