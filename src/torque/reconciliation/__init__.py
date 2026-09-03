"""Module 7 — Payment Reconciliation & Attribution (Blueprint §7).

Consumes already-verified success `Event`s from Module 2's pipeline (§7.3 — no
webhook path of its own), matches them to open `RevenueLeakCase`s, decides
`AGENT_ASSISTED` vs `SELF_RECOVERED` vs `AMBIGUOUS`, re-splits `ActionCase`
credit for merged outreach, and closes cases (`RECOVERED` /
`PARTIALLY_RECOVERED`, or `CANCELLED` when the customer self-paid before Torque
could act).

Public surface:
* `reconcile_event(session, *, event_id)` / `ReconcileOutcome` — the engine.
* `RECONCILE_EVENT_TYPES` — the success event types it handles.
"""

from torque.reconciliation.reconcile import (
    RECONCILE_EVENT_TYPES,
    ReconcileOutcome,
    reconcile_event,
)

__all__ = ["RECONCILE_EVENT_TYPES", "ReconcileOutcome", "reconcile_event"]
