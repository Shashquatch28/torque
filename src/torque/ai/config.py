"""AI subsystem configuration — Phase 0 (feature-flag / disableability).

Same pattern as `torque.config.Settings` / `torque.config.PolicyConfig`
(`BaseSettings` + `SettingsConfigDict` + a cached accessor) — kept in its own
module under `torque.ai` rather than added to `torque.config` so the AI
package's configuration surface stays self-contained with the rest of the
package boundary.

`AISettings.enabled` is the master switch for the AI subsystem. Nothing in
the deterministic core (ingestion, diagnosis, scoring, guardrails, execution)
reads this flag anywhere — the AI layer is additive and post-hoc by
construction (no import from it exists on that path), so this flag has
nothing to disable there. It exists now so that a future phase's API router
has a single, already-tested place to check before exposing any AI endpoint.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TORQUE_AI_", extra="ignore")

    #: Master on/off switch for the AI subsystem. Defaults to disabled — the
    #: AI layer must be explicitly opted into, never on by default.
    enabled: bool = False


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()


__all__ = ["AISettings", "get_ai_settings"]
