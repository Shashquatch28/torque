"""The outcome of resolving one buffered `payment.failed` `Event` (Milestone 7b).

In its own module so `buffer` and `cases` can both import it without a cycle.
"""

from __future__ import annotations

from enum import Enum, auto


class BufferOutcome(Enum):
    #: Nothing to do — Event missing, already `processed`, not `payment.failed`,
    #: or a case already exists for it (idempotent redelivery).
    NOOP = auto()
    #: A later `payment.captured` for the same payment/order arrived in the
    #: interim — `Event.processed = True`, no case (same-session self-recovery).
    SELF_RECOVERED = auto()
    #: A new `PAYMENT_DEGRADATION` case was created.
    CASE_CREATED = auto()
    #: A new case was created AND an open `CHECKOUT_ABANDONMENT` case was
    #: superseded into it (§2.4 Merge).
    CASE_MERGED = auto()
