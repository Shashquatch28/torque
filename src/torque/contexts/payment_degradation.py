"""`PaymentDegradationContext` — Blueprint Section 3.

Fields: `decline_code, gateway, retry_count, is_hard_decline`.

NOTE: `network_directive` (MAC / tier) is a TOP-LEVEL field on
`RevenueLeakCase`, not nested here — every module checks it without a context
parse.

`is_hard_decline` is `bool | None` (Milestone 7b): ingestion sets it to `None`
("not yet classified") and the Diagnosis Engine (Module 3) owns the hard/soft
determination. Nothing in Module 2 classifies it.

`merged_abandonment_context` (Milestone 7b) carries the context of a
`CHECKOUT_ABANDONMENT` case that cross-leg dedup (§2.4) superseded into this
one — "the abandonment's context is appended into the surviving case's
diagnostic input for Module 3, no signal thrown away". Its value is a
`CheckoutAbandonmentContext` payload that was already validated when the
superseded case was written, so it is typed-at-origin; it is declared here as a
plain dict only to avoid a context-module import cycle.
"""

from __future__ import annotations

from pydantic import ConfigDict

from torque.contexts.registry import LegContext


class PaymentDegradationContext(LegContext):
    model_config = ConfigDict(extra="forbid")

    decline_code: str | None = None
    gateway: str
    retry_count: int = 0
    is_hard_decline: bool | None = None
    merged_abandonment_context: dict | None = None
