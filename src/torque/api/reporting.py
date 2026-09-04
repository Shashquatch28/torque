"""Module 9 — the read-only reporting HTTP surface (Blueprint §9.10).

A single `APIRouter`, same conventions as the Module 2 webhook routes: FastAPI,
`Depends(get_db)`, the merchant named in the path, every query tenant-scoped via
`torque.reporting.metrics` (which goes through `TenantScope`). No writes, no side
effects — `get_db` still commits on a clean return but these handlers issue only
`SELECT`s.

Endpoints (the six the future UI needs, §9.10):

* `GET /reports/{merchant_id}/summary`         — merchant- or batch-level totals
* `GET /reports/{merchant_id}/report`          — the §9.4 batch bundle
* `GET /reports/{merchant_id}/by-intervention` — by leg (default) or action type
* `GET /reports/{merchant_id}/over-time`       — recovery time series
* `GET /reports/{merchant_id}/exceptions`      — operational / exception report
* `GET /reports/{merchant_id}/cases`           — case-level list (paginated)
* `GET /reports/{merchant_id}/cases/{case_id}` — one case, with its actions
* `GET /reports/{merchant_id}/cases/{case_id}/events` — the explainability stream

`opened_from` / `opened_to` (ISO-8601) bound a *batch* on `opened_at`;
`closed_from` / `closed_to` bound the time series on `closed_at`. All windows are
half-open `[from, to)` so adjacent windows never double-count (D-119).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from torque.api.deps import get_db
from torque.enums import CaseStatus, LegType
from torque.models import Merchant
from torque.reporting import metrics
from torque.reporting.metrics import ReportWindow
from torque.reporting.schemas import (
    ActivityFeed,
    CaseDetail,
    CaseEventEntry,
    CaseList,
    HumanQueueList,
    InterventionBreakdown,
    LegBreakdown,
    OperationalReport,
    RecoveryReport,
    RecoverySummary,
    TimeBucket,
    TopCaseList,
)

router = APIRouter(prefix="/reports/{merchant_id}", tags=["reporting"])


def _require_merchant(session: Session, merchant_id: str) -> None:
    if session.get(Merchant, merchant_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown merchant {merchant_id!r}")


def _window(start: datetime | None, end: datetime | None) -> ReportWindow | None:
    if start is None and end is None:
        return None
    return ReportWindow(start=start, end=end)


def _leg(leg: str | None) -> LegType | None:
    if leg is None:
        return None
    try:
        return LegType(leg)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"unknown leg_type {leg!r}") from exc


def _status(status: str | None) -> CaseStatus | None:
    if status is None:
        return None
    try:
        return CaseStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"unknown status {status!r}") from exc


@router.get("/summary", response_model=RecoverySummary)
def get_summary(
    merchant_id: str,
    opened_from: datetime | None = None,
    opened_to: datetime | None = None,
    leg: str | None = None,
    session: Session = Depends(get_db),
) -> RecoverySummary:
    _require_merchant(session, merchant_id)
    return metrics.recovery_summary(
        session, merchant_id, window=_window(opened_from, opened_to), leg=_leg(leg)
    )


@router.get("/report", response_model=RecoveryReport)
def get_report(
    merchant_id: str,
    opened_from: datetime | None = None,
    opened_to: datetime | None = None,
    leg: str | None = None,
    session: Session = Depends(get_db),
) -> RecoveryReport:
    _require_merchant(session, merchant_id)
    return metrics.recovery_report(
        session, merchant_id, window=_window(opened_from, opened_to), leg=_leg(leg)
    )


@router.get("/by-intervention")
def get_by_intervention(
    merchant_id: str,
    by: Literal["leg", "action_type"] = "leg",
    opened_from: datetime | None = None,
    opened_to: datetime | None = None,
    session: Session = Depends(get_db),
) -> list[LegBreakdown] | list[InterventionBreakdown]:
    _require_merchant(session, merchant_id)
    window = _window(opened_from, opened_to)
    if by == "action_type":
        return metrics.recovery_by_action_type(session, merchant_id, window=window)
    return metrics.recovery_by_leg(session, merchant_id, window=window)


@router.get("/over-time", response_model=list[TimeBucket])
def get_over_time(
    merchant_id: str,
    bucket: Literal["day", "week", "month"] = "day",
    closed_from: datetime | None = None,
    closed_to: datetime | None = None,
    session: Session = Depends(get_db),
) -> list[TimeBucket]:
    _require_merchant(session, merchant_id)
    return metrics.recovery_over_time(
        session, merchant_id, window=_window(closed_from, closed_to), bucket=bucket
    )


@router.get("/exceptions", response_model=OperationalReport)
def get_exceptions(
    merchant_id: str,
    opened_from: datetime | None = None,
    opened_to: datetime | None = None,
    session: Session = Depends(get_db),
) -> OperationalReport:
    _require_merchant(session, merchant_id)
    return metrics.operational_exceptions(
        session, merchant_id, window=_window(opened_from, opened_to)
    )


@router.get("/cases", response_model=CaseList)
def get_cases(
    merchant_id: str,
    leg: str | None = None,
    status: str | None = None,
    opened_from: datetime | None = None,
    opened_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> CaseList:
    _require_merchant(session, merchant_id)
    return metrics.list_cases(
        session,
        merchant_id,
        window=_window(opened_from, opened_to),
        leg=_leg(leg),
        status=_status(status),
        limit=limit,
        offset=offset,
    )


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(
    merchant_id: str,
    case_id: uuid.UUID,
    session: Session = Depends(get_db),
) -> CaseDetail:
    _require_merchant(session, merchant_id)
    detail = metrics.case_detail(session, merchant_id, case_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="case not found for this merchant")
    return detail


@router.get("/cases/{case_id}/events", response_model=list[CaseEventEntry])
def get_case_events(
    merchant_id: str,
    case_id: uuid.UUID,
    session: Session = Depends(get_db),
) -> list[CaseEventEntry]:
    _require_merchant(session, merchant_id)
    stream = metrics.case_event_stream(session, merchant_id, case_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="case not found for this merchant")
    return stream


# --- Module 10 read endpoints (§10.4 / §10.7 / §10.17) -----------------


@router.get("/top-at-risk", response_model=TopCaseList)
def get_top_at_risk(
    merchant_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
) -> TopCaseList:
    """§10.4 — open cases ranked by Module 8's `recovery_score` (backend order)."""
    _require_merchant(session, merchant_id)
    return metrics.top_at_risk_cases(session, merchant_id, limit=limit)


@router.get("/human-queue", response_model=HumanQueueList)
def get_human_queue(
    merchant_id: str,
    session: Session = Depends(get_db),
) -> HumanQueueList:
    """§10.7 — the Agent Console queue, ordered by the entry's stored priority."""
    _require_merchant(session, merchant_id)
    return metrics.human_queue_list(session, merchant_id)


@router.get("/activity", response_model=ActivityFeed)
def get_activity(
    merchant_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> ActivityFeed:
    """§10.17 — recent `CaseEvent`s across the merchant, newest first (the
    polling source for the live feed)."""
    _require_merchant(session, merchant_id)
    return metrics.recent_activity(session, merchant_id, limit=limit)
