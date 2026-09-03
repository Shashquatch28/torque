"""Step-timing computation — Blueprint §5 (D-025 says Module 5 implements it).

Two distinct concerns, deliberately not conflated (§5.2.5):

* **step offset** — *when the step is due*: the previous step's actual completion
  time plus the node's `timing_offset_hours`, OR — when the merchant's payday
  policy gate is on and the diagnosis emitted `suggested_timing_adjustment` — the
  payday-substituted target instead of the static offset (§4.3, the runtime
  substitution D-025 assigns here).
* **`allowed_hours`** — *when execution may happen*: a fire time landing outside
  the contact window is **deferred** to the next window opening (never fires
  early, never silently skips — §5.2.5). It constrains *when*, it never rewrites
  the underlying offset.

All wall-clock reasoning is in IST (Torque is India-only; `allowed_hours` is IST
per D-024). Inputs/outputs are timezone-aware UTC. `allowed_hours` supports
overnight windows (`start > end`, e.g. 22:00–06:00).
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, time, timedelta

from torque.compliance.retry_rails import IST, UPI_PEAK_WINDOWS_IST
from torque.diagnosis.root_causes import PAYDAY_TIMING_HINT

_HHMM = "%H:%M"


def _parse_hhmm(value: str) -> time:
    return datetime.strptime(value, _HHMM).time()


def _in_window(t: time, start: time, end: time) -> bool:
    """Is IST wall-clock `t` inside `[start, end]`? Handles overnight windows
    (`start > end` spans midnight). Bounds inclusive."""
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


def _defer_into_window(base_ist: datetime, start: time, end: time) -> datetime:
    """Move `base_ist` forward to the next moment inside `[start, end]` (or return
    it unchanged if already inside). Never moves backward."""
    if _in_window(base_ist.time(), start, end):
        return base_ist
    opening = base_ist.replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0
    )
    if opening <= base_ist:
        opening += timedelta(days=1)
    return opening


def next_month_end_working_day(from_utc: datetime) -> datetime:
    """The next occurrence of "last working day of the month" strictly after
    `from_utc`, at 09:00 IST — the §3.4 payday heuristic Module 5 resolves.

    Weekends (Sat/Sun) step back to the preceding Friday. If this month's
    month-end working day is already at/behind `from_utc`, the next month's is
    used. Returned as timezone-aware UTC (the caller still applies `allowed_hours`).
    """
    ist = from_utc.astimezone(IST)
    year, month = ist.year, ist.month

    def _mewd(y: int, m: int) -> datetime:
        day = calendar.monthrange(y, m)[1]
        d = datetime(y, m, day, 9, 0, tzinfo=IST)
        while d.weekday() >= 5:  # 5=Sat, 6=Sun
            d -= timedelta(days=1)
        return d

    candidate = _mewd(year, month)
    if candidate <= ist:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        candidate = _mewd(year, month)
    return candidate.astimezone(UTC)


def compute_fire_time(
    *,
    previous_completion: datetime,
    timing_offset_hours: float,
    allowed_start: str,
    allowed_end: str,
    payday_adjustment: str | None = None,
) -> datetime:
    """When the next step should fire (UTC, timezone-aware).

    `previous_completion` — actual completion of the prior step (or the run's
    creation time for the entry step). `payday_adjustment` — the value the Module
    4 payday gate resolved (`torque.policy.payday.effective_timing_adjustment`);
    when it is the payday hint, the static offset is replaced by the payday target
    (§4.3). Either way the result is deferred into `allowed_hours`.
    """
    if payday_adjustment == PAYDAY_TIMING_HINT:
        base = next_month_end_working_day(previous_completion)
    else:
        base = previous_completion + timedelta(hours=timing_offset_hours)

    start, end = _parse_hhmm(allowed_start), _parse_hhmm(allowed_end)
    fire_ist = _defer_into_window(base.astimezone(IST), start, end)
    return fire_ist.astimezone(UTC)


def next_upi_execution_time(now: datetime) -> datetime:
    """The next UTC instant at/after `now` that is OUTSIDE every NPCI peak window
    — the re-defer target when a UPI AutoPay retry is claimed inside a peak window
    (§5.2.2; peak windows are closed intervals per `within_upi_execution_window`).
    """
    ist = now.astimezone(IST)
    t = ist.time()
    for start, end in UPI_PEAK_WINDOWS_IST:
        if start <= t <= end:
            reopen = ist.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
            reopen += timedelta(minutes=1)  # just past the closed interval's end
            return reopen.astimezone(UTC)
    return now


def within_allowed_hours(now: datetime, allowed_start: str, allowed_end: str) -> bool:
    """Is `now` inside the contact window? Used at execution time to re-verify a
    claimed job is still in-window (poller lag / clock drift) before firing."""
    start, end = _parse_hhmm(allowed_start), _parse_hhmm(allowed_end)
    return _in_window(now.astimezone(IST).time(), start, end)


def next_window_opening(now: datetime, allowed_start: str, allowed_end: str) -> datetime:
    """The next UTC instant `now` (or later) falls inside `allowed_hours` — the
    re-defer target when a claimed job is found out-of-window at execution time."""
    start, end = _parse_hhmm(allowed_start), _parse_hhmm(allowed_end)
    return _defer_into_window(now.astimezone(IST), start, end).astimezone(UTC)
