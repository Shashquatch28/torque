"""`SubscriptionFailureContext` — Blueprint Section 3.

Fields: `mandate_id, mandate_type, billing_cycle, subscription_id`.

There is deliberately NO `pre_debit_notified_at` field here — per-attempt
pre-debit tracking lives in the `PreDebitNotification` table (Milestone 2).
`extra="forbid"` means an attempt to write `pre_debit_notified_at` into this
context is rejected.
"""

from __future__ import annotations

from pydantic import ConfigDict

from torque.contexts.registry import LegContext
from torque.enums import MandateType


class SubscriptionFailureContext(LegContext):
    model_config = ConfigDict(extra="forbid")

    mandate_id: str
    mandate_type: MandateType
    billing_cycle: str
    subscription_id: str
