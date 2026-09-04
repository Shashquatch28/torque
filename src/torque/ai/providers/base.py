"""The provider-agnostic structured-generation interface.

`torque.ai.narrative.explain_case` receives an `LLMProvider` instance as a
parameter (dependency injection) — it never constructs, imports, or
branches on a concrete provider type. Every implementation (mock, a future
local/free model, a future real API-backed provider) satisfies exactly this
interface, and nothing else. This is what keeps `narrative.py` provider-
agnostic and keeps the standard test suite network-independent (it always
injects `MockProvider`, never a real one).

`structured_generate` is `async` because a real, network-backed provider is
I/O-bound; `explain_case` is `async` for the same reason, even though
Phase 4's only implementation (`MockProvider`) performs no real I/O. This
diverges from the rest of the (synchronous, `SQLAlchemy`-`Session`-based)
codebase deliberately — it is the one async boundary in `torque.ai`, matched
to the one genuinely I/O-bound operation in the package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMProvider(ABC):
    """Provider-agnostic structured-generation interface."""

    @abstractmethod
    async def structured_generate(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int,
        timeout_s: float,
    ) -> BaseModel:
        """Generate output conforming to `schema` from a `(system, user)`
        message pair.

        Implementations are expected to RAISE on failure (timeout, network
        error, an upstream response that cannot be parsed into `schema`) —
        a provider is not responsible for degrading gracefully; that is
        `torque.ai.narrative.explain_case`'s job, which catches every
        exception raised here and converts it into a single, safe
        `torque.ai.exceptions.NarrativeGenerationError`.
        """

    @abstractmethod
    def provider_id(self) -> str:
        """A stable string identifying this provider/model, disclosed on
        every generated `CaseNarrative.provider_id` for reproducibility.
        Synchronous and side-effect-free — a real provider's id (e.g.
        `"anthropic:claude-sonnet-5"`) is static configuration, never a
        network round trip."""


__all__ = ["LLMProvider"]
