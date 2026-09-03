"""Module 6 — Compliance & Cross-Leg Guardrail Engine (Blueprint §6).

The canonical, callable home for the guardrail decision Module 5 consults, plus
the two things that do not fit inside a single `Action` check — escalation-ceiling
handling and human-queue routing — and the Outreach Coordinator (Part A §5,
operationally owned here, §6.1).

Ownership boundary (§6.2): **Module 5 executes actions and owns the atomic write;
Module 6 owns the decision of whether an action is allowed to happen at all.**

Layout (kept execution-package-free — Q-J):

* `guardrail_engine` — `GuardrailEngine.check()`, the single facade. Composes the
  existing pure predicates (`torque.execution.guardrails`, `torque.compliance.*`,
  `outreach_coordinator`); returns the four-way `GuardDecision` (D-097 / Q-A).
* `outreach_coordinator` — priority (Module 8 seam), the 4h cross-leg quiet
  period, open-conversation suspension, the two WhatsApp gates.
* `human_queue` — the persistent FIFO-per-merchant queue (§6.4) + its three
  feeders.
* `merge` — the live merge path (imported by the poll batch, not re-exported
  here, to keep the import graph acyclic).

Escalation-ceiling enforcement (§6.3) lives in the runner's lifecycle (it must
run inside the execution tick's transaction) but is a Module 6 policy decision —
see `torque.execution.runner._escalation_ceiling_hit`.
"""

from torque.coordination.guardrail_engine import GuardrailEngine
from torque.coordination.human_queue import (
    HumanQueueReason,
    enqueue,
    list_for_merchant,
    route_broken_promise,
    sweep_escalated_to_human,
)
from torque.coordination.outreach_coordinator import (
    OUTREACH_ACTIONS,
    cross_leg_quiet_period_defer,
    open_conversation_defer,
    priority,
    whatsapp_gate,
)

__all__ = [
    "GuardrailEngine",
    "HumanQueueReason",
    "OUTREACH_ACTIONS",
    "cross_leg_quiet_period_defer",
    "enqueue",
    "list_for_merchant",
    "open_conversation_defer",
    "priority",
    "route_broken_promise",
    "sweep_escalated_to_human",
    "whatsapp_gate",
]
