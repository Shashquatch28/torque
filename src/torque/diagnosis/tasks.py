"""Celery task for Module 3 — Diagnosis Engine.

Diagnosis is short-lived, stateless work (a few lookups + one transaction) — the
same class of work Module 2's ingestion tasks are, and explicitly the kind the
blueprint routes through the lightweight queue rather than Temporal (§5.5: "never
used for anything that needs to survive more than a few seconds of delay"; that
durability requirement is what `PlaybookRun` uses Temporal for — Module 5, U-07).

Thin on purpose, mirroring `torque.ingestion.tasks`: open one transactional
`session_scope()`, delegate to `diagnose_case`, return a short string for
logs / eager-mode assertions. `_session_scope` is a module-level indirection so
tests can bind the task to the harness session.

**Module 12a (D-137, resolves D-080/D-088).** The Module 2 → Module 3 automatic
*enqueue* is now wired — see `torque.ingestion.tasks._dispatch_diagnosis`, which
calls this task. Symmetrically, this task is the Module 3 → Module 4 trigger:
once `diagnose_case`'s own transaction has committed (i.e. **after** the `with`
block below — never from inside an open transaction), a
`DiagnosisOutcome.ROUTED_TO_PLAYBOOK` result dispatches
`torque.policy.activate_case_task` for the same case. `ESCALATED` and `NOOP`
dispatch nothing — an escalated case is done (a human takes it from here) and a
`NOOP` diagnosed nothing. `_dispatch_activation` is its own module-level name so
tests can monkeypatch it exactly like `_session_scope`.
"""

from __future__ import annotations

import uuid

from torque.db.session import session_scope
from torque.diagnosis.engine import DiagnosisOutcome, diagnose_case
from torque.ingestion.celery_app import celery_app

_session_scope = session_scope


def _dispatch_activation(case_id: str) -> None:
    """Enqueue policy activation for a just-diagnosed, routed case (D-137)."""
    from torque.policy.tasks import activate_case_task

    activate_case_task.apply_async((case_id,))


@celery_app.task(name="torque.diagnosis.diagnose_case", ignore_result=True)
def diagnose_case_task(case_id: str) -> str:
    """Diagnose one case by id (Blueprint Module 3). Idempotent under redelivery."""
    with _session_scope() as session:
        outcome = diagnose_case(session, case_id=uuid.UUID(str(case_id)))
    if outcome is DiagnosisOutcome.ROUTED_TO_PLAYBOOK:
        _dispatch_activation(str(case_id))
    return outcome.name
