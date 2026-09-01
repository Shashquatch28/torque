"""`CheckoutAbandonmentContext` — Blueprint Section 3.

Fields: `cart_id, cart_value, drop_stage, payment_method_attempted`.

`payment_method_attempted = UPI_COLLECT` dropped at VPA entry has a known,
specific recovery action (suggest Intent Flow) — a signal-derived recommendation
no generic cart-recovery tool can make.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import ConfigDict

from torque.contexts.registry import LegContext
from torque.enums import PaymentMethodAttempted


class CheckoutAbandonmentContext(LegContext):
    model_config = ConfigDict(extra="forbid")

    cart_id: str
    cart_value: Decimal
    drop_stage: str
    payment_method_attempted: PaymentMethodAttempted
