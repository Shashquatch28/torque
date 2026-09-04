"""Torque AI layer — a read-only intelligence surface over the deterministic core.

**Phase 0 + Phase 1 only**, as of this package's current state. See
`documentation/ai-memory/AI_BLUEPRINT.md` for the full phase roadmap and its
"Current Implementation Status" section — do not assume any capability beyond
what that section marks complete.

Architectural principle (non-negotiable — enforced by
`tests/test_ai_boundary.py`, not merely stated here):

    Deterministic Torque decides.
    AI reads and explains.
    AI does not mutate Torque business state.

Nothing under `torque.ai` imports `torque.state_machine`, `torque.coordination`,
`torque.events`, `torque.agent_console`, `torque.execution`, `torque.ingestion`,
`torque.policy`, `torque.diagnosis`, `torque.scoring`, `torque.reconciliation`,
`torque.promises`, or `torque.api` — every one of those either transitions a
case, executes an action, writes a `CaseEvent`, or otherwise mutates business
state (or, for `torque.api`, wires up the routers that call into them). This
package has no write path to any of them — structurally, not just by
convention or code review.

As of Phase 0 + Phase 1, the only capability implemented is
`torque.ai.evidence.gather_case_evidence` — a read-only projection of one
case's authoritative state into the `torque.ai.schemas` DTOs. There is no
retrieval, no embedding, no LLM call, no citation-bearing generated prose, no
shadow ML model, and no API endpoint yet. All of that is future, separately
approved phases (see `AI_BLUEPRINT.md`).
"""

from __future__ import annotations
