"""Leg-context base class and the `leg_type -> model` registry.

`validate_context` is the single entry point used by the ORM guard
(`torque.models.guards`) before any `RevenueLeakCase` row is flushed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from torque.enums import LegType
from torque.exceptions import ContextValidationError


class LegContext(BaseModel):
    """Base for every typed leg context. `extra="forbid"` is set on each concrete
    subclass too, but declaring it here documents the intent: nothing untyped."""

    model_config = ConfigDict(extra="forbid")


def validate_context(leg_type: LegType, raw: dict) -> dict:
    """Validate `raw` against the model for `leg_type` and return the normalised
    JSON-safe dict that will actually be persisted.

    `B2B_RECEIVABLE` carries no context blob — a non-empty dict is rejected.
    """
    model = CONTEXT_MODELS.get(LegType(leg_type))
    if model is None:  # B2B_RECEIVABLE
        if raw:
            raise ContextValidationError(
                "B2B_RECEIVABLE cases take no context blob (see B2BInvoice); "
                f"got keys {sorted(raw)}"
            )
        return {}
    try:
        parsed = model.model_validate(raw)
    except ValidationError as exc:
        raise ContextValidationError(
            f"invalid context for {leg_type}: {exc.errors(include_url=False)}"
        ) from exc
    return parsed.model_dump(mode="json")


# Concrete models imported at the bottom so they can `from ... import LegContext`
# above without a circular-import failure. Re-exported for `torque.contexts`.
from torque.contexts.checkout_abandonment import CheckoutAbandonmentContext  # noqa: E402
from torque.contexts.payment_degradation import PaymentDegradationContext  # noqa: E402
from torque.contexts.subscription_failure import SubscriptionFailureContext  # noqa: E402

__all__ = [
    "LegContext",
    "validate_context",
    "CONTEXT_MODELS",
    "CheckoutAbandonmentContext",
    "PaymentDegradationContext",
    "SubscriptionFailureContext",
]

CONTEXT_MODELS: dict[LegType, type[BaseModel] | None] = {
    LegType.PAYMENT_DEGRADATION: PaymentDegradationContext,
    LegType.CHECKOUT_ABANDONMENT: CheckoutAbandonmentContext,
    LegType.SUBSCRIPTION_FAILURE: SubscriptionFailureContext,
    LegType.B2B_RECEIVABLE: None,
}
