"""`PaymentDegradationContext` — Blueprint Section 3.

Fields: `decline_code, gateway, retry_count, is_hard_decline`.

NOTE: `network_directive` (MAC / tier) is a TOP-LEVEL field on
`RevenueLeakCase`, not nested here — every module checks it without a context
parse.
"""

from __future__ import annotations

from pydantic import ConfigDict

from torque.contexts.registry import LegContext


class PaymentDegradationContext(LegContext):
    model_config = ConfigDict(extra="forbid")

    decline_code: str | None = None
    gateway: str
    retry_count: int = 0
    is_hard_decline: bool = False
