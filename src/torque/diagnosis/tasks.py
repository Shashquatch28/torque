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

NOTE (Module 2 → Module 3 handoff): wiring the automatic *enqueue* of this task
from the ingestion legs is deliberately NOT done in Module 3 — see D-080. In
eager test mode an inline enqueue would run diagnosis synchronously inside
ingestion and change Module 2's tested post-ingestion contract (cases end
`DETECTED`). The engine + task are the finished, independently-invocable Module 3
surface; the cross-module trigger is an orchestration-layer concern.
"""

from __future__ import annotations

import uuid

from torque.db.session import session_scope
from torque.diagnosis.engine import diagnose_case
from torque.ingestion.celery_app import celery_app

_session_scope = session_scope


@celery_app.task(name="torque.diagnosis.diagnose_case", ignore_result=True)
def diagnose_case_task(case_id: str) -> str:
    """Diagnose one case by id (Blueprint Module 3). Idempotent under redelivery."""
    with _session_scope() as session:
        outcome = diagnose_case(session, case_id=uuid.UUID(str(case_id)))
    return outcome.name
