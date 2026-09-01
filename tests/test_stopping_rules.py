"""Blueprint Section 3 / Section 4.2 / decision D - typed stopping-rules models.
Pure, no DB."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from torque.exceptions import PlaybookValidationError
from torque.playbooks import (
    AllowedHours,
    PartialStoppingRules,
    parse_partial_stopping_rules,
    parse_stopping_rules,
)

BASE = {
    "max_attempts": 3,
    "max_duration_days": 7,
    "allowed_hours": {"start": "08:00", "end": "19:00"},
    "escalation_ceiling": 2,
}


def test_valid_stopping_rules():
    r = parse_stopping_rules(BASE)
    assert r.max_attempts == 3
    assert r.allowed_hours.end == "19:00"


@pytest.mark.parametrize("good", ["00:00", "08:00", "09:05", "19:00", "23:59"])
def test_allowed_hours_accepts_hhmm(good):
    AllowedHours(start=good, end="23:00")


@pytest.mark.parametrize("bad", ["8:00", "08:0", "25:00", "08:60", "0800", "08:00 IST", "8am"])
def test_allowed_hours_rejects_bad_format(bad):
    with pytest.raises(ValidationError):
        AllowedHours(start=bad, end="10:00")


def test_allowed_hours_rejects_tz_key():
    with pytest.raises(ValidationError):
        AllowedHours.model_validate({"start": "08:00", "end": "19:00", "tz": "IST"})


@pytest.mark.parametrize("field", ["max_attempts", "max_duration_days", "escalation_ceiling"])
def test_positive_bounds(field):
    bad = {**BASE, field: 0}
    with pytest.raises(PlaybookValidationError):
        parse_stopping_rules(bad)


def test_unknown_key_rejected():
    with pytest.raises(PlaybookValidationError):
        parse_stopping_rules({**BASE, "cooldown": 5})


def test_missing_field_rejected():
    incomplete = {k: v for k, v in BASE.items() if k != "escalation_ceiling"}
    with pytest.raises(PlaybookValidationError):
        parse_stopping_rules(incomplete)


# --- PartialStoppingRules (override) --------------------------------


def test_partial_all_optional():
    p = parse_partial_stopping_rules({})
    assert p.model_dump(exclude_none=True) == {}


def test_partial_single_field():
    p = parse_partial_stopping_rules({"max_attempts": 5})
    assert p.max_attempts == 5
    assert p.max_duration_days is None


def test_partial_rejects_unknown_key():
    with pytest.raises(PlaybookValidationError):
        parse_partial_stopping_rules({"max_attempts": 5, "bogus": 1})


def test_partial_rejects_bad_bound():
    with pytest.raises(PlaybookValidationError):
        parse_partial_stopping_rules({"max_attempts": 0})


def test_partial_allowed_hours_typed():
    p = PartialStoppingRules.model_validate({"allowed_hours": {"start": "09:00", "end": "18:00"}})
    assert p.allowed_hours.start == "09:00"
