"""Pure predicates for `SystemicEvent` - Blueprint Section 3 / Decision J.

No detection job, no failure-rate rollups, no rolling-baseline computation, no
case transitions - those are Module 2 Section 2.5. These are the two checkable
rules Module 2 will call. Side-effect-free.
"""

from __future__ import annotations


def systemic_threshold_breached(
    *,
    failure_rate: float,
    baseline_rate: float,
    absolute_count: int,
    baseline_floor: float,
    absolute_floor: int,
    multiplier: float,
) -> bool:
    """The Section 3 compound threshold - ALL three conditions must hold:

        failure_rate     >= multiplier * baseline_rate     (the spike)
        baseline_rate    >= baseline_floor  (N)            (cold-start guard)
        absolute_count   >= absolute_floor  (M)            (cold-start guard)

    `multiplier` is the spike factor (Decision J: 5x). `baseline_floor` (N) and
    `absolute_floor` (M) are per-scope config values
    (`PolicyConfig.systemic_baseline_floor_per_min` /
    `PolicyConfig.systemic_absolute_count_floor`). The caller is responsible for
    computing `failure_rate` / `baseline_rate` / `absolute_count` over the
    detection window (Module 2 Section 2.5); this function only compares.
    """
    return (
        failure_rate >= multiplier * baseline_rate
        and baseline_rate >= baseline_floor
        and absolute_count >= absolute_floor
    )


def systemic_resolved(
    *, minutes_below_threshold: float, sustain_window_minutes: float
) -> bool:
    """The Section 3 resolution rule: `SystemicEvent.resolved_at` may be written
    only after the failure rate has stayed below threshold for a full sustain
    window (Decision J default 10 min,
    `PolicyConfig.systemic_sustain_window_minutes`). Prevents
    SYSTEMIC_HOLD -> DIAGNOSING -> SYSTEMIC_HOLD flapping on intermittent
    outages.
    """
    return minutes_below_threshold >= sustain_window_minutes
