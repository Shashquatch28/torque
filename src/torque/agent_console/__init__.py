"""Module 10 — Agent Console human write-back (Blueprint §4 / §10.8).

The one place a human agent's decision on a queued case becomes a state change.
`ESCALATED_TO_HUMAN` "carries `escalation_resolution`, written by a human agent,
driving the final transition" (§4) — implemented here as:

* `resolve_escalation` — `ESCALATED_TO_HUMAN → {RECOVERED, PARTIALLY_RECOVERED,
  WRITTEN_OFF}` (all three edges already legal in `state_machine.py`), plus
  `escalation_resolution` / `_by` / `_at`, a `HUMAN_RESOLVED` `CaseEvent`, and
  removal from the human queue. A recovering resolution also records
  `recovered_amount` / `recovery_type = AGENT_ASSISTED` inside
  `guards.human_resolution_writer`.
* `pause_case` / `unpause_case` — `PLAYBOOK_ACTIVE ↔ PAUSED` for queue cases
  still inside a playbook (broken-promise / open-conversation feeds), matching
  the §4 "merchant intervening manually" edge.

Queue priority and the recovery score are consumed, never recomputed
(Module 6 / Module 8 stay authoritative).
"""

from __future__ import annotations

from torque.agent_console.resolve import (
    EscalationResolution,
    ResolveOutcome,
    pause_case,
    resolve_escalation,
    unpause_case,
)

__all__ = [
    "EscalationResolution",
    "ResolveOutcome",
    "pause_case",
    "resolve_escalation",
    "unpause_case",
]
