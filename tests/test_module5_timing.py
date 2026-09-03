"""Module 5 — timing engine (Blueprint §5.2.5 / §4.3 / D-025). Pure, no DB."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from torque.compliance.retry_rails import IST
from torque.execution import timing


# 2026-09-03 is a Thursday.
def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def _ist(dt):
    return dt.astimezone(IST)


def test_offset_from_previous_completion_in_window():
    # 06:00 UTC = 11:30 IST; +2h = 13:30 IST, inside 09–21 → unchanged.
    fire = timing.compute_fire_time(
        previous_completion=_utc(2026, 9, 3, 6),
        timing_offset_hours=2,
        allowed_start="09:00",
        allowed_end="21:00",
    )
    assert _ist(fire).strftime("%H:%M") == "13:30"


def test_offset_deferred_into_next_window():
    # 11:30 IST + 20h = 07:30 IST next day, before 09:00 → deferred to 09:00 IST.
    fire = timing.compute_fire_time(
        previous_completion=_utc(2026, 9, 3, 6),
        timing_offset_hours=20,
        allowed_start="09:00",
        allowed_end="21:00",
    )
    assert _ist(fire).strftime("%H:%M") == "09:00"
    assert _ist(fire).date().day == 4


def test_deferral_never_fires_early():
    # A fire time landing before the window opens moves FORWARD, never backward.
    fire = timing.compute_fire_time(
        previous_completion=_utc(2026, 9, 3, 1),  # 06:30 IST
        timing_offset_hours=0,
        allowed_start="09:00",
        allowed_end="21:00",
    )
    assert fire >= _utc(2026, 9, 3, 1)
    assert _ist(fire).strftime("%H:%M") == "09:00"


def test_overnight_window():
    # Window 22:00–06:00 (spans midnight). 02:00 IST is inside → unchanged.
    fire = timing.compute_fire_time(
        previous_completion=_utc(2026, 9, 2, 20, 30),  # 02:00 IST next day
        timing_offset_hours=0,
        allowed_start="22:00",
        allowed_end="06:00",
    )
    assert timing.within_allowed_hours(fire, "22:00", "06:00")
    # 12:00 IST is outside → deferred forward to 22:00 IST.
    fire2 = timing.compute_fire_time(
        previous_completion=_utc(2026, 9, 3, 6, 30),  # 12:00 IST
        timing_offset_hours=0,
        allowed_start="22:00",
        allowed_end="06:00",
    )
    assert _ist(fire2).strftime("%H:%M") == "22:00"


def test_within_allowed_hours_boundary():
    assert timing.within_allowed_hours(_utc(2026, 9, 3, 3, 30), "09:00", "21:00")  # 09:00 IST
    assert not timing.within_allowed_hours(_utc(2026, 9, 3, 3, 29), "09:00", "21:00")  # 08:59


def test_payday_substitutes_month_end_working_day():
    # payday hint replaces the static offset with the month-end working day.
    fire = timing.compute_fire_time(
        previous_completion=_utc(2026, 9, 3, 6),
        timing_offset_hours=1,  # ignored under payday
        allowed_start="09:00",
        allowed_end="21:00",
        payday_adjustment="next_month_end_working_day",
    )
    d = _ist(fire)
    assert (d.year, d.month, d.day) == (2026, 9, 30)  # Wed 30 Sep 2026
    assert d.weekday() < 5


def test_payday_rolls_to_next_month_when_this_month_passed():
    # After 2026-09-30, the next month-end working day is October's.
    fire = timing.next_month_end_working_day(_utc(2026, 9, 30, 12))
    d = _ist(fire)
    assert d.month == 10
    assert d.weekday() < 5


def test_payday_month_end_steps_back_over_weekend():
    # 2026-05-31 is a Sunday → month-end working day is Fri 2026-05-29.
    fire = timing.next_month_end_working_day(_utc(2026, 5, 1, 0))
    d = _ist(fire)
    assert (d.month, d.day) == (5, 29)
    assert d.weekday() == 4  # Friday


@pytest.mark.parametrize(
    ("ist_hour", "in_peak"),
    [(11, True), (12, True), (13, True), (14, False), (18, True), (22, False), (9, False)],
)
def test_upi_execution_window(ist_hour, in_peak):
    from torque.compliance.retry_rails import within_upi_execution_window

    # Build a UTC time that is `ist_hour`:00 IST.
    utc = datetime(2026, 9, 3, ist_hour, 0, tzinfo=IST).astimezone(UTC)
    assert within_upi_execution_window(utc) is (not in_peak)


def test_next_upi_execution_time_leaves_peak():
    # 12:00 IST is inside the 10:00–13:00 peak → reschedule past 13:00 IST.
    noon_ist = datetime(2026, 9, 3, 12, 0, tzinfo=IST).astimezone(UTC)
    nxt = timing.next_upi_execution_time(noon_ist)
    assert _ist(nxt).strftime("%H:%M") == "13:01"
