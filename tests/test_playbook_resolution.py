"""Blueprint Section 4.2 / decision 6 - deep_merge + effective_stopping_rules.
Pure, no DB."""

from __future__ import annotations

import pytest

from torque.exceptions import PlaybookValidationError
from torque.playbooks import deep_merge, effective_stopping_rules

BASE = {
    "max_attempts": 3,
    "max_duration_days": 7,
    "allowed_hours": {"start": "08:00", "end": "19:00"},
    "escalation_ceiling": 2,
}


def test_none_override_returns_base_copy():
    out = deep_merge(BASE, None)
    assert out == BASE
    assert out is not BASE
    assert out["allowed_hours"] is not BASE["allowed_hours"]


def test_empty_override_returns_base():
    assert deep_merge(BASE, {}) == BASE


def test_scalar_override_replaces():
    assert deep_merge(BASE, {"max_attempts": 5})["max_attempts"] == 5


def test_nested_dict_deep_merges():
    out = deep_merge(BASE, {"allowed_hours": {"end": "20:00"}})
    assert out["allowed_hours"] == {"start": "08:00", "end": "20:00"}


def test_list_replaced_wholesale_not_element_merged():
    base = {"channels": ["whatsapp", "email"], "x": {"a": 1, "b": 2}}
    out = deep_merge(base, {"channels": ["sms"], "x": {"b": 9}})
    assert out["channels"] == ["sms"]  # replaced, not ["whatsapp","email","sms"]
    assert out["x"] == {"a": 1, "b": 9}  # dict deep-merged


def test_does_not_mutate_inputs():
    override = {"allowed_hours": {"end": "20:00"}}
    deep_merge(BASE, override)
    assert BASE["allowed_hours"]["end"] == "19:00"
    assert override == {"allowed_hours": {"end": "20:00"}}


# --- effective_stopping_rules ------------------------------------


def test_effective_with_no_override_is_base():
    r = effective_stopping_rules(BASE, None)
    assert r.max_attempts == 3


def test_effective_applies_override_and_validates():
    r = effective_stopping_rules(BASE, {"max_attempts": 4, "allowed_hours": {"start": "10:00"}})
    assert r.max_attempts == 4
    assert r.allowed_hours.start == "10:00"
    assert r.allowed_hours.end == "19:00"


def test_effective_raises_on_invalid_merged_result():
    with pytest.raises(PlaybookValidationError):
        effective_stopping_rules(BASE, {"max_attempts": 0})
