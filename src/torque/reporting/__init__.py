"""Module 9 — Reporting & Measurement (Blueprint §9).

Turns Torque's event stream and reconciliation outcomes into business-level
recovery measurement: *how much revenue was at risk, how much was recovered,
how it was recovered, and what happened to the rest.*

* `metrics` — the derivation functions (pure, tenant-scoped, no persisted
  aggregate). Module 7 stays authoritative for attribution; Module 9 only reads
  `recovery_type` / `recovered_amount`.
* `schemas` — the pydantic result/response contract.

The HTTP surface is `torque.api.reporting` (a read-only `APIRouter`, the same
FastAPI conventions as the Module 2 webhook routes).

**Descriptive, not causal.** This module reports what happened. Incrementality
lift, Wilson confidence intervals, and SUTVA-adjusted lift (Blueprint §9.1) are
deferred — see D-121. The `in_control_cohort` / `control_group` data they need is
already collected and untouched.
"""

from __future__ import annotations

from torque.reporting.metrics import (
    ReportWindow,
    case_detail,
    case_event_stream,
    human_queue_list,
    list_cases,
    operational_exceptions,
    recent_activity,
    recovery_by_action_type,
    recovery_by_leg,
    recovery_by_recovery_type,
    recovery_over_time,
    recovery_report,
    recovery_summary,
    top_at_risk_cases,
)

__all__ = [
    "ReportWindow",
    "case_detail",
    "case_event_stream",
    "human_queue_list",
    "list_cases",
    "operational_exceptions",
    "recent_activity",
    "recovery_by_action_type",
    "recovery_by_leg",
    "recovery_by_recovery_type",
    "recovery_over_time",
    "recovery_report",
    "recovery_summary",
    "top_at_risk_cases",
]
