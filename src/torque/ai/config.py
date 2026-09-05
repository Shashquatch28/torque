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
`torque.ai.narrative.explain_case` itself does NOT check `enabled` — it
stays fully callable/testable regardless, exactly like every other
`torque.ai` function; gating *exposure* is an API-layer concern (Phase 6,
not built yet), not something baked into the generation function itself.

**Phase 4 additions.** `max_tokens` / `timeout_s` are the default generation
budget `torque.ai.narrative.explain_case` passes to
`LLMProvider.structured_generate` when the caller doesn't override them —
genuinely consumed, not decorative (see `narrative.py`). `TORQUE_AI_PROVIDER`
(a provider-selection setting) was considered and deliberately NOT added
here: Phase 4 has no provider-selection/factory function to consume it (only
`MockProvider`, always explicitly injected by the caller) — adding it now
would be exactly the "configuration that is not actually consumed" this
module's own convention warns against. It belongs to whichever future phase
adds a real provider factory (likely Phase 6's API layer).

**Phase 8 hardening.** `max_tokens`/`timeout_s` now carry a `gt=0` lower
bound. Since Phase 8 also made `explain_case` enforce `timeout_s` itself
(via `asyncio.wait_for`, not merely passing it to the provider), a
misconfigured `TORQUE_AI_TIMEOUT_S=0` or a negative value from the
environment would otherwise make every generation call fail instantly (or,
for `max_tokens`, ask a real future provider for a nonsensical budget) —
this rejects that misconfiguration at settings-construction time, with a
clear Pydantic validation error, rather than a confusing runtime failure
mode discovered later.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TORQUE_AI_", extra="ignore")

    #: Master on/off switch for the AI subsystem. Defaults to disabled — the
    #: AI layer must be explicitly opted into, never on by default.
    enabled: bool = False

    #: Default max-tokens budget for a `structured_generate` call. A real
    #: provider's own hard ceiling still applies underneath this.
    max_tokens: int = Field(default=2000, gt=0)

    #: Default timeout (seconds) for a `structured_generate` call. Generation
    #: is post-hoc and off any critical path — this bounds a single call, not
    #: the whole request lifecycle. Enforced by `explain_case` itself as of
    #: Phase 8, not merely passed to the provider — see `narrative.py`.
    timeout_s: float = Field(default=30.0, gt=0)


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()


__all__ = ["AISettings", "get_ai_settings"]
