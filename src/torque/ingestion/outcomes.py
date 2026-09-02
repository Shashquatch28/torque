"""The outcome of resolving one ingested `Event` across the four Module 2 legs.

In its own module so every ingestion path can import it without a cycle.
"""

from __future__ import annotations

from enum import Enum, auto


class BufferOutcome(Enum):
    #: Nothing to do — Event missing, already `processed`, wrong type for this
    #: path, or a case already exists for it (idempotent redelivery).
    NOOP = auto()
    #: A later success signal for the same payment/subscription arrived in the
    #: interim — `Event.processed = True`, no case (same-session self-recovery).
    SELF_RECOVERED = auto()
    #: A new canonical `RevenueLeakCase` was created for this leg.
    CASE_CREATED = auto()
    #: A new case was created and immediately superseded into an existing case
    #: of the other leg, OR an existing case absorbed the new one (§2.4 Merge,
    #: either direction). The canonical case is reachable via
    #: `superseded_by_case_id`.
    CASE_MERGED = auto()
    #: A `B2BInvoice` was bundled into an existing open `B2B_RECEIVABLE` case
    #: (§3 grouping rule) — no new case created.
    CASE_ATTACHED = auto()
