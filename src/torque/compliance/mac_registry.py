"""Pure lookup against `MacCodeRegistry` (Blueprint Section 3 / Section 5.3)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.enums import MacTier, Network
from torque.models.mac_code_registry import MacCodeRegistry


def tier_for(session: Session, network: Network, mac_code: str) -> MacTier | None:
    """Return the behaviour tier for a raw network decline-advice code, or
    ``None`` if the code is not seeded.

    The "unseeded code -> default TIER_2_CAPPED_RETRY + write a flagged
    CaseEvent" fallback is Module 5's job (Section 5.3); this function stays a
    pure lookup and leaves that decision to the caller.
    """
    return session.scalar(
        select(MacCodeRegistry.tier)
        .where(MacCodeRegistry.network == Network(network))
        .where(MacCodeRegistry.mac_code == mac_code)
    )
