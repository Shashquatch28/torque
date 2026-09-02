"""Systemic detection & suppression — Blueprint §2.5 (Milestone 7c).

`NETWORK_WIDE` tier only. `ISSUER_SPECIFIC` is deferred: no issuer / BIN /
acquirer / route field exists on `Event`, on any leg context, or on
`RevenueLeakCase`, so per-issuer aggregation cannot be done faithfully (see
`UNRESOLVED.md` U-08).

The 60-second Celery-beat task (`torque.ingestion.tasks.detect_systemic_task`)
calls `run_systemic_detection` inside one `session_scope()` transaction.

Per merchant, per run:

* **detect** — trailing-`systemic_detection_window_minutes` `payment.failed`
  rate vs. a trailing-`systemic_baseline_days` average that **excludes the live
  detection window** (so the current spike cannot inflate its own baseline);
  the compound rule is the existing `compliance.systemic.systemic_threshold_breached`
  predicate, used verbatim. On breach, and only if no active `NETWORK_WIDE`
  `SystemicEvent` exists for the merchant, create one and sweep every open
  `DETECTED` case (`systemic_event_id IS NULL`) into `SYSTEMIC_HOLD` via
  `transition_case` (`STATUS_CHANGED`) plus a `SYSTEMIC_HOLD_APPLIED` `CaseEvent`.
* **resolve** — for each active `SystemicEvent`, recompute the trailing-
  `systemic_sustain_window_minutes` rate; if it is below `multiplier × baseline`
  the existing `systemic_resolved` predicate passes, `resolved_at` is written,
  and every case held by *that* event transitions `SYSTEMIC_HOLD -> DIAGNOSING`.
  `systemic_event_id` is left populated (audit linkage).

`apply_active_hold_if_any` is the §2.7 ingestion hook: a case created by the
M7b buffer while a `NETWORK_WIDE` event is active is born held, not `DETECTED`.

Every read and write is scoped to one merchant; there is no cross-merchant
aggregation. Repeated execution is idempotent — see the guards in
`_detect_and_hold` / `_check_and_resolve`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from torque.compliance.systemic import systemic_resolved, systemic_threshold_breached
from torque.config import get_policy
from torque.db.scoped import TenantScope
from torque.enums import Actor, CaseEventType, CaseStatus, SystemicScope
from torque.events.case_event_writer import append_case_event
from torque.models import Event, RevenueLeakCase, SystemicEvent
from torque.state_machine import transition_case

_PAYMENT_FAILED = "payment.failed"
_HOLD_TRIGGER = "systemic_network_wide"
_RESUME_TRIGGER = "systemic_resolved"


# --- rollup helpers -----------------------------------------------------------


def _failure_count(
    session: Session, *, merchant_id: str, start: datetime, end: datetime
) -> int:
    """`payment.failed` events for one merchant in the half-open window
    `[start, end)`."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.merchant_id == merchant_id)
            .where(Event.type == _PAYMENT_FAILED)
            .where(Event.received_at >= start)
            .where(Event.received_at < end)
        )
        or 0
    )


def _baseline_failure_rate(session: Session, *, merchant_id: str, now: datetime) -> float:
    """Trailing-`systemic_baseline_days` average failures/min, computed over
    `[now - baseline_days, now - detection_window)` — the live detection window
    is excluded so a current spike cannot inflate its own baseline."""
    policy = get_policy()
    window_minutes = policy.systemic_detection_window_minutes
    start = now - timedelta(days=policy.systemic_baseline_days)
    end = now - timedelta(minutes=window_minutes)
    minutes = policy.systemic_baseline_days * 24 * 60 - window_minutes
    if minutes <= 0:
        return 0.0
    return _failure_count(session, merchant_id=merchant_id, start=start, end=end) / minutes


# --- per-merchant detection -------------------------------------------------


def _hold_case(session: Session, *, case: RevenueLeakCase, systemic_event: SystemicEvent) -> None:
    case.systemic_event_id = systemic_event.systemic_event_id
    transition_case(
        session,
        case,
        CaseStatus.SYSTEMIC_HOLD,
        trigger=_HOLD_TRIGGER,
        actor=Actor.SYSTEM,
    )
    append_case_event(
        session,
        case_id=case.case_id,
        event_type=CaseEventType.SYSTEMIC_HOLD_APPLIED,
        payload={
            "systemic_event_id": str(systemic_event.systemic_event_id),
            "scope": SystemicScope.NETWORK_WIDE.value,
            "issuer_code": None,
        },
        actor=Actor.SYSTEM,
        counterparty_id=case.counterparty_id,
    )


def _active_network_wide_event(session: Session, *, merchant_id: str) -> SystemicEvent | None:
    return session.scalars(
        select(SystemicEvent)
        .where(SystemicEvent.merchant_id == merchant_id)
        .where(SystemicEvent.scope == SystemicScope.NETWORK_WIDE)
        .where(SystemicEvent.resolved_at.is_(None))
    ).first()


def _detect_and_hold(session: Session, *, merchant_id: str, now: datetime) -> None:
    policy = get_policy()
    window_minutes = policy.systemic_detection_window_minutes
    window_start = now - timedelta(minutes=window_minutes)

    window_failures = _failure_count(
        session, merchant_id=merchant_id, start=window_start, end=now
    )
    failure_rate = window_failures / window_minutes
    baseline_rate = _baseline_failure_rate(session, merchant_id=merchant_id, now=now)

    # Idempotency: never a second active NETWORK_WIDE event for one merchant.
    if _active_network_wide_event(session, merchant_id=merchant_id) is not None:
        return

    if not systemic_threshold_breached(
        failure_rate=failure_rate,
        baseline_rate=baseline_rate,
        absolute_count=window_failures,
        baseline_floor=policy.systemic_baseline_floor_per_min,
        absolute_floor=policy.systemic_absolute_count_floor,
        multiplier=policy.systemic_spike_multiplier,
    ):
        return

    scope = TenantScope(session, merchant_id)
    systemic_event = SystemicEvent(
        scope=SystemicScope.NETWORK_WIDE,
        issuer_code=None,
        network=None,
        failure_rate_at_detection=Decimal(str(failure_rate)),
        detected_at=now,
        resolved_at=None,
        affected_case_count=0,
    )
    scope.add(systemic_event)
    session.flush()  # assigns systemic_event_id

    held = 0
    for case in session.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == merchant_id)
        .where(RevenueLeakCase.status == CaseStatus.DETECTED)
        .where(RevenueLeakCase.systemic_event_id.is_(None))
    ).all():
        _hold_case(session, case=case, systemic_event=systemic_event)
        held += 1

    systemic_event.affected_case_count = held
    session.flush()


def _check_and_resolve(session: Session, *, merchant_id: str, now: datetime) -> None:
    policy = get_policy()
    active_events = session.scalars(
        select(SystemicEvent)
        .where(SystemicEvent.merchant_id == merchant_id)
        .where(SystemicEvent.resolved_at.is_(None))
    ).all()
    if not active_events:
        return

    sustain = policy.systemic_sustain_window_minutes
    recent_failures = _failure_count(
        session,
        merchant_id=merchant_id,
        start=now - timedelta(minutes=sustain),
        end=now,
    )
    recent_rate = recent_failures / sustain
    baseline_rate = _baseline_failure_rate(session, merchant_id=merchant_id, now=now)
    threshold = policy.systemic_spike_multiplier * baseline_rate

    # Stateless aggregate (approved design): if the trailing sustain-window rate
    # is below threshold, treat the whole window as "below" — no per-minute
    # persistence state, no `below_threshold_since` column.
    minutes_below = float(sustain) if recent_rate < threshold else 0.0
    if not systemic_resolved(
        minutes_below_threshold=minutes_below, sustain_window_minutes=sustain
    ):
        return

    for systemic_event in active_events:
        systemic_event.resolved_at = now
        for case in session.scalars(
            select(RevenueLeakCase)
            .where(RevenueLeakCase.status == CaseStatus.SYSTEMIC_HOLD)
            .where(RevenueLeakCase.systemic_event_id == systemic_event.systemic_event_id)
        ).all():
            transition_case(
                session,
                case,
                CaseStatus.DIAGNOSING,
                trigger=_RESUME_TRIGGER,
                actor=Actor.SYSTEM,
            )
        # systemic_event_id is deliberately left populated (audit linkage).
    session.flush()


# --- entry points ---------------------------------------------------------


def run_systemic_detection(session: Session, *, now: datetime | None = None) -> None:
    """One pass of §2.5 across every merchant with recent failures or an active
    `SystemicEvent`. The caller owns the transaction (the Celery task's
    `session_scope`)."""
    now = now or datetime.now(UTC)
    policy = get_policy()
    window_start = now - timedelta(minutes=policy.systemic_detection_window_minutes)

    detect_merchants = set(
        session.scalars(
            select(Event.merchant_id)
            .where(Event.type == _PAYMENT_FAILED)
            .where(Event.received_at >= window_start)
            .distinct()
        )
    )
    resolve_merchants = set(
        session.scalars(
            select(SystemicEvent.merchant_id)
            .where(SystemicEvent.resolved_at.is_(None))
            .distinct()
        )
    )

    for merchant_id in detect_merchants:
        _detect_and_hold(session, merchant_id=merchant_id, now=now)
    for merchant_id in resolve_merchants:
        _check_and_resolve(session, merchant_id=merchant_id, now=now)


def apply_active_hold_if_any(session: Session, case: RevenueLeakCase) -> None:
    """§2.7 ingestion hook: if a `NETWORK_WIDE` `SystemicEvent` is active for
    `case.merchant_id`, hold the freshly-created case (`DETECTED -> SYSTEMIC_HOLD`)
    instead of leaving it `DETECTED`. A no-op when no event is active — the M7b
    path is then behaviourally unchanged."""
    if CaseStatus(case.status) is not CaseStatus.DETECTED or case.systemic_event_id is not None:
        return
    active = _active_network_wide_event(session, merchant_id=case.merchant_id)
    if active is None:
        return
    _hold_case(session, case=case, systemic_event=active)
