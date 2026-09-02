"""Cross-leg dedup — Blueprint §2.4, Decision D (Merge).

M7b implements the **one live direction**: a `payment.failed` arriving after an
existing `CHECKOUT_ABANDONMENT` case. The reverse (`checkout.abandoned` arriving
after a payment-degradation case) is deferred with Leg-2 ingestion.

`find_supersedable_case` returns the open, non-terminal `CHECKOUT_ABANDONMENT`
case for the same `(merchant_id, counterparty_id)` whose `context.cart_id`
matches the payment's `order_id`, opened within
`PolicyConfig.cross_leg_dedup_window_hours` (default 2h). Candidate narrowing is
by index-friendly columns; the `cart_id` match is done in Python (no JSONB
index — demo scale).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.config import get_policy
from torque.enums import LegType
from torque.models import RevenueLeakCase
from torque.state_machine import is_terminal


def find_supersedable_case(
    session: Session,
    *,
    merchant_id: str,
    counterparty_id,
    order_id: str | None,
    now: datetime,
) -> RevenueLeakCase | None:
    if not order_id:
        return None

    window_hours = get_policy().cross_leg_dedup_window_hours
    cutoff = now - timedelta(hours=window_hours)

    candidates = session.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == merchant_id)
        .where(RevenueLeakCase.counterparty_id == counterparty_id)
        .where(RevenueLeakCase.leg_type == LegType.CHECKOUT_ABANDONMENT)
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
        .where(RevenueLeakCase.opened_at >= cutoff)
        .order_by(RevenueLeakCase.opened_at.desc())
    )
    for case in candidates:
        if is_terminal(case.status, case.leg_type):
            continue
        if (case.context or {}).get("cart_id") == order_id:
            return case
    return None
