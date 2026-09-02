"""Cross-leg dedup — Blueprint §2.4, Decision D (Merge). **Bidirectional.**

The check runs symmetrically: whichever case would be created *second* looks for
an open, non-terminal case of the *other* type for the same
`(merchant_id, counterparty_id)` correlated on `cart_id == order_id`, opened
within `PolicyConfig.cross_leg_dedup_window_hours` (default 2h). If found, the
`CHECKOUT_ABANDONMENT` case (narrower, less diagnostically specific) is the one
that ends up superseded (`superseded_by_case_id`) and the `PAYMENT_DEGRADATION`
case is canonical — regardless of which arrived first.

* `find_supersedable_case` — a `payment.failed` arrives second: find the open
  `CHECKOUT_ABANDONMENT` case whose `context.cart_id` matches the payment's
  `order_id` (Leg 1, `cases.create_or_attach_case`).
* `find_supersedable_payment_case` — a `checkout.abandoned` arrives second: find
  the open `PAYMENT_DEGRADATION` case whose originating `Event`'s `order_id`
  matches the abandonment's `cart_id` (Leg 2, `checkout.create_checkout_case`).
  The payment case stores no `cart_id` in its own typed context, so the match is
  against its `source_event.raw_payload`.

Candidate narrowing is by index-friendly columns (`merchant_id`,
`counterparty_id`, `leg_type`, `opened_at`); the id match is done in Python —
**no JSONB expression index** (demo scale).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.config import get_policy
from torque.enums import LegType
from torque.ingestion import payloads
from torque.models import Event, RevenueLeakCase
from torque.state_machine import is_terminal


def _window_cutoff(now: datetime) -> datetime:
    return now - timedelta(hours=get_policy().cross_leg_dedup_window_hours)


def find_supersedable_case(
    session: Session,
    *,
    merchant_id: str,
    counterparty_id,
    order_id: str | None,
    now: datetime,
) -> RevenueLeakCase | None:
    """Leg-1 direction: an open `CHECKOUT_ABANDONMENT` case whose
    `context.cart_id == order_id`."""
    if not order_id:
        return None

    candidates = session.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == merchant_id)
        .where(RevenueLeakCase.counterparty_id == counterparty_id)
        .where(RevenueLeakCase.leg_type == LegType.CHECKOUT_ABANDONMENT)
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
        .where(RevenueLeakCase.opened_at >= _window_cutoff(now))
        .order_by(RevenueLeakCase.opened_at.desc())
    )
    for case in candidates:
        if is_terminal(case.status, case.leg_type):
            continue
        if (case.context or {}).get("cart_id") == order_id:
            return case
    return None


def find_supersedable_payment_case(
    session: Session,
    *,
    merchant_id: str,
    counterparty_id,
    cart_id: str | None,
    now: datetime,
) -> RevenueLeakCase | None:
    """Leg-2 direction: an open `PAYMENT_DEGRADATION` case whose originating
    `Event`'s `order_id` matches the abandonment's `cart_id`."""
    if not cart_id:
        return None

    candidates = session.scalars(
        select(RevenueLeakCase)
        .where(RevenueLeakCase.merchant_id == merchant_id)
        .where(RevenueLeakCase.counterparty_id == counterparty_id)
        .where(RevenueLeakCase.leg_type == LegType.PAYMENT_DEGRADATION)
        .where(RevenueLeakCase.superseded_by_case_id.is_(None))
        .where(RevenueLeakCase.opened_at >= _window_cutoff(now))
        .order_by(RevenueLeakCase.opened_at.desc())
    )
    for case in candidates:
        if is_terminal(case.status, case.leg_type):
            continue
        src = session.get(Event, case.source_event_id)
        if src is not None and payloads.order_id(src.raw_payload or {}) == cart_id:
            return case
    return None
