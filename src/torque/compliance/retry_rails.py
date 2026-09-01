"""Pure predicates for the three retry rails — Blueprint Section 2.6 / Section 3.

Card / UPI AutoPay / NACH are governed by three structurally different bodies.
None of these functions is a template for the others.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from torque.enums import ClearingCycleStatus

# --- Card: Mastercard dual-window volume caps ------------------------------
# Network constants, NOT merchant-configurable. Pre-retry check (Section 3):
#   attempts_used_24h < 10 AND attempts_used_30d < 35 AND hard_stop = false
CARD_ATTEMPTS_24H_CAP = 10
CARD_ATTEMPTS_30D_CAP = 35

# --- UPI AutoPay: NPCI hard cap -------------------------------------------
# 1 original + 3 retries = 4 total. NPCI-enforced, not merchant-configurable.
UPI_AUTOPAY_HARD_CAP = 3

# NPCI declared PEAK windows, IST. Treated as CLOSED intervals (decision 5):
# an attempt exactly at 13:00:00 or 21:30:00 is INSIDE peak and blocked.
IST = timezone(timedelta(hours=5, minutes=30))
UPI_PEAK_WINDOWS_IST: tuple[tuple[time, time], ...] = (
    (time(10, 0), time(13, 0)),
    (time(17, 0), time(21, 30)),
)


def card_retry_within_budget(
    *, attempts_used_24h: int, attempts_used_30d: int, hard_stop: bool
) -> bool:
    """True when a card RETRY_PAYMENT is permitted by `CardRetryBudget`
    (Section 3 pre-retry check). First-failure-wins: any one condition fails
    -> not permitted."""
    return (
        not hard_stop
        and attempts_used_24h < CARD_ATTEMPTS_24H_CAP
        and attempts_used_30d < CARD_ATTEMPTS_30D_CAP
    )


def upi_attempt_gate_open(
    *, attempts_used: int, mandate_cancelled_at: datetime | None
) -> bool:
    """UPI AutoPay gate 1 of 2 (Section 3): the attempt-count gate.
    `attempts_used < 3 AND mandate_cancelled_at IS NULL`.
    (`attempts_used` includes the original attempt.)"""
    return attempts_used < UPI_AUTOPAY_HARD_CAP and mandate_cancelled_at is None


def within_upi_execution_window(when: datetime) -> bool:
    """UPI AutoPay gate 2 of 2 (Section 3): the execution-window gate.

    True when NPCI's infrastructure will accept the debit attempt itself —
    i.e. `when` is OUTSIDE both peak windows. This is a different concern from
    `Playbook.stopping_rules.allowed_hours` (when it is acceptable to *contact*
    the customer).

    An aware datetime is converted to IST; a naive datetime is assumed to
    already be IST wall-clock time. Peak windows are closed intervals.
    """
    if when.tzinfo is not None:
        when = when.astimezone(IST)
    t = when.time()
    return not any(start <= t <= end for start, end in UPI_PEAK_WINDOWS_IST)


def nach_retry_eligible(
    *,
    clearing_cycle_status: ClearingCycleStatus | str,
    dishonour_count_this_fy: int,
    retry_eligible_after: date | None,
    ceiling: int,
    as_of: date,
) -> bool:
    """NACH representment eligibility (Section 3).

    NACH has no NPCI cap, so this applies Torque's *self-imposed* ceiling plus
    the batch-clearing gate. Eligible only when ALL hold:
      * the previous attempt has RETURNED (a PENDING_CLEARING or CLEARED status
        means there is nothing to represent right now);
      * `dishonour_count_this_fy < ceiling` (the merchant-configurable ceiling,
        recommended default 3 — see `PolicyConfig.nach_representment_ceiling_default`);
      * the next batch clearing window has arrived (`as_of >= retry_eligible_after`).
    """
    if ClearingCycleStatus(clearing_cycle_status) is not ClearingCycleStatus.RETURNED:
        return False
    if dishonour_count_this_fy >= ceiling:
        return False
    if retry_eligible_after is not None and as_of < retry_eligible_after:
        return False
    return True
