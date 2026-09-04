"""LLM provider abstraction — Phase 4.

`torque.ai.narrative` never imports a concrete provider; it receives one
injected by the caller as an `LLMProvider`. `MockProvider` is the only
concrete implementation as of Phase 4 — the standard test suite's default,
requiring no network access, no API key, and no external service. A real
provider (Anthropic or otherwise) is deferred; see
`documentation/ai-memory/AI_BLUEPRINT.md` and `DECISIONS.md` for why.
"""

from __future__ import annotations

from torque.ai.providers.base import LLMProvider
from torque.ai.providers.mock_provider import MockProvider

__all__ = ["LLMProvider", "MockProvider"]
