"""Module 3 — Diagnosis Engine (Blueprint §3).

Converts a Module-2 canonical `RevenueLeakCase` into `root_cause_code`,
`root_cause_label`, `diagnosis_confidence`, `suggested_timing_adjustment`, and
(PAYMENT_DEGRADATION only) `is_hard_decline`, then routes it by the `T = 0.65`
confidence threshold to `PLAYBOOK_ACTIVE` or `ESCALATED_TO_HUMAN`.

Public surface:
* `diagnose_case(session, case_id=...)` — the orchestrator (idempotent, atomic).
* `DiagnosisOutcome` — its return enum.
* `RootCauseCode` — the Module-3-owned `root_cause_code` vocabulary (§3.1).
"""

from __future__ import annotations

from torque.diagnosis.engine import DiagnosisOutcome, diagnose_case
from torque.diagnosis.root_causes import RootCauseCode

__all__ = ["DiagnosisOutcome", "RootCauseCode", "diagnose_case"]
