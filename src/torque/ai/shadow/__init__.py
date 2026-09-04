"""Phase 7 — Shadow ML (observational, non-authoritative).

    Deterministic Torque decides. AI reads and explains. Shadow ML watches.

This subpackage adds one more capability to that second sentence: a small,
CPU-only baseline model that predicts whether an already-diagnosed case will
eventually recover, trained on Torque's own historical, terminal cases. It
inherits every architectural constraint `torque.ai`'s package boundary
already enforces (see `torque/ai/__init__.py` and
`tests/test_ai_boundary.py`) and adds one more of its own:

    A shadow prediction is never read by anything that decides. It exists
    only to be trained, scored, and evaluated for its own sake.

Concretely, nothing in this subpackage (or anywhere else in `torque.ai`)
calls `torque.state_machine.transition_case`, writes a `RevenueLeakCase`
column, creates an `Action`, sends a communication, or is consulted by
`torque.coordination.outreach_coordinator.priority`,
`torque.policy.activate_case`, `torque.diagnosis.diagnose_case`, or any
other deterministic decision path. `ShadowPrediction` (see
`torque.ai.shadow.schemas`) always carries a non-optional `disclaimer` and
`n_training_cases` field precisely so a caller cannot render a number
without the caveat attached.

Module layout:

    labels.py      — pure: the training-eligible-population / recovered-
                     label definitions (mirrors `torque.state_machine` and
                     `torque.reporting.incrementality` logic locally, per
                     the same documented-duplication discipline
                     `torque.ai.retrieval` already established — see that
                     module's docstring for the full rationale).
    schemas.py     — the DTO contract: `ShadowFeatureVector`,
                     `ShadowTrainingExample`, `ShadowPrediction`,
                     `ShadowClassificationMetrics`, `ShadowTrainingReport`.
    features.py    — DB-touching: `extract_features()` /
                     `build_shadow_dataset()`, reading through
                     `torque.db.scoped.TenantScope` exactly like
                     `torque.ai.evidence`/`torque.ai.retrieval` already do.
                     Deliberately a *separate, narrower* function from
                     `torque.ai.evidence.gather_case_evidence` — see that
                     module's `CaseSnapshot` leakage-boundary note and
                     `documentation/ai-memory/AI_BLUEPRINT.md` §11.
    model.py       — pure (no DB, no I/O): the replaceable `ShadowModel`
                     interface + the one baseline implementation.
    evaluation.py  — pure: deterministic classification metrics + a
                     majority-class baseline comparison.
    training.py    — orchestration: dataset -> temporal split -> fit ->
                     evaluate -> `ShadowTrainingReport`.
    scoring.py     — orchestration: score one case with an already-fitted
                     model -> `ShadowPrediction`.

Same forbidden-import boundary as the rest of `torque.ai` (unchanged,
untouched by this phase): no `torque.state_machine`, `torque.coordination`,
`torque.events`, `torque.agent_console`, `torque.execution`,
`torque.ingestion`, `torque.policy`, `torque.diagnosis`, `torque.scoring`,
`torque.reconciliation`, `torque.promises`, or `torque.api` — enforced by
`tests/test_ai_boundary.py`, which discovers this subpackage automatically
(`AI_PACKAGE.rglob("*.py")` is recursive) with no test-file change needed.
"""

from __future__ import annotations
