"""Counterparty resolution for an ingestion-created case.

Match strategy (Blueprint has no identity spec; this is the M7b default):
exact `phone` first, then exact `email`, then create. `Counterparty` is the
single global PII store (D-002/D-003) — matched/created through the raw session;
`Merchant_Counterparty` is tenant-scoped and goes through `TenantScope`.

KNOWN LIMITATION: phone-first / email-second exact matching can create a
duplicate real-world identity if a person changes phone *and* email between
signals. This is a stated identity-resolution limitation, not a compliance
failure — erasure and consent still operate correctly per row.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.db.scoped import TenantScope
from torque.models import Counterparty, MerchantCounterparty


def find_counterparty(
    session: Session, *, phone: str | None, email: str | None
) -> Counterparty | None:
    """Match-only counterparty lookup (exact `phone` first, then exact `email`).
    Returns `None` when neither matches — used by Module 7 reconciliation, which
    must **not** create an identity for an inbound payment signal."""
    if phone:
        cp = session.scalars(
            select(Counterparty).where(Counterparty.phone == phone)
        ).first()
        if cp is not None:
            return cp
    if email:
        return session.scalars(
            select(Counterparty).where(Counterparty.email == email)
        ).first()
    return None


def resolve_counterparty(
    session: Session,
    *,
    merchant_id: str,
    phone: str | None,
    email: str | None,
) -> tuple[Counterparty, MerchantCounterparty]:
    cp: Counterparty | None = None
    if phone:
        cp = session.scalars(
            select(Counterparty).where(Counterparty.phone == phone)
        ).first()
    if cp is None and email:
        cp = session.scalars(
            select(Counterparty).where(Counterparty.email == email)
        ).first()
    if cp is None:
        # New identity — consent defaults must be safe (no nudge, no WhatsApp).
        cp = Counterparty(
            name=None,
            phone=phone,
            email=email,
            payment_failure_nudge_consent=False,
            whatsapp_opt_in=False,
        )
        session.add(cp)
        session.flush()

    scope = TenantScope(session, merchant_id)
    mc = session.scalars(
        select(MerchantCounterparty)
        .where(MerchantCounterparty.merchant_id == merchant_id)
        .where(MerchantCounterparty.counterparty_id == cp.counterparty_id)
    ).first()
    if mc is None:
        mc = MerchantCounterparty(counterparty_id=cp.counterparty_id)
        scope.add(mc)  # stamps merchant_id
        session.flush()
    return cp, mc
