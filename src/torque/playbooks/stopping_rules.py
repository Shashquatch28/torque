"""`stopping_rules` typed models (Blueprint Section 3 / Section 4.2).

`allowed_hours` is `{ "start": "HH:MM", "end": "HH:MM" }` — 24-hour, **no
per-record timezone** (decision D). Torque is India-only; IST is a system-wide
constant handled in the policy layer (see Module 5's defer logic when it lands).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from torque.exceptions import PlaybookValidationError

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class AllowedHours(BaseModel):
    """A fully-specified contact window. `start` / `end` both required."""

    model_config = ConfigDict(extra="forbid")

    start: str = Field(pattern=_HHMM)
    end: str = Field(pattern=_HHMM)


class PartialAllowedHours(BaseModel):
    """An `allowed_hours` fragment inside a `MerchantPlaybookConfig` override -
    either bound may be omitted; the missing side is filled from the base
    playbook by `deep_merge`, and the merged result is validated as a full
    `AllowedHours`."""

    model_config = ConfigDict(extra="forbid")

    start: str | None = Field(default=None, pattern=_HHMM)
    end: str | None = Field(default=None, pattern=_HHMM)


class StoppingRules(BaseModel):
    """The full, resolved stopping rules for a playbook run."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(ge=1)
    max_duration_days: int = Field(ge=1)
    allowed_hours: AllowedHours
    escalation_ceiling: int = Field(ge=1)


class PartialStoppingRules(BaseModel):
    """A `MerchantPlaybookConfig.stopping_rules_override` — any subset of the
    `StoppingRules` fields. Deep-merged onto the base before full validation."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int | None = Field(default=None, ge=1)
    max_duration_days: int | None = Field(default=None, ge=1)
    allowed_hours: PartialAllowedHours | None = None
    escalation_ceiling: int | None = Field(default=None, ge=1)


def parse_stopping_rules(raw: dict) -> StoppingRules:
    try:
        return StoppingRules.model_validate(raw)
    except ValidationError as exc:
        raise PlaybookValidationError(
            f"malformed stopping_rules: {exc.errors(include_url=False)}"
        ) from exc


def parse_partial_stopping_rules(raw: dict) -> PartialStoppingRules:
    try:
        return PartialStoppingRules.model_validate(raw)
    except ValidationError as exc:
        raise PlaybookValidationError(
            f"malformed stopping_rules_override: {exc.errors(include_url=False)}"
        ) from exc
