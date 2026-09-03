"""Pure extractors over a Razorpay `payment_link.*` webhook payload — Module 7.

Side-effect-free, no DB. Every function tolerates a missing key. The `payment.*`
and `subscription.*` fields Module 7 also reads (`payment_id`, `amount_rupees`,
`contact_phone`, `contact_email`, `subscription_id`) are reused from
`torque.ingestion.payloads` — not duplicated here.

Razorpay `payment_link.paid` / `.partially_paid` / `.expired` / `.cancelled` body:

    { "event": "payment_link.paid",
      "payload": {
        "payment_link": { "entity": {
            "id": "plink_...", "amount": 50000, "amount_paid": 50000,
            "status": "paid", "reference_id": "...",
            "notes": { "torque_case_id": "<uuid>" },
            "customer": { "contact": "+91...", "email": "..." } } },
        "payment": { "entity": { "id": "pay_...", "amount": 50000, ... } } } }

`amount` fields are in paise; the `*_rupees` helpers convert to a 2dp `Decimal`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def payment_link_entity(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        entity = payload["payload"]["payment_link"]["entity"]
    except (KeyError, TypeError):
        return {}
    return entity if isinstance(entity, dict) else {}


def payment_link_id(payload: dict[str, Any]) -> str | None:
    v = payment_link_entity(payload).get("id")
    return v or None


def payment_link_status(payload: dict[str, Any]) -> str | None:
    """The lowercase Razorpay link status (`issued` / `partially_paid` / `paid` /
    `expired` / `cancelled`), or `None`."""
    v = payment_link_entity(payload).get("status")
    return str(v).lower() if v else None


def payment_link_amount_paid_rupees(payload: dict[str, Any]) -> Decimal:
    raw = payment_link_entity(payload).get("amount_paid")
    try:
        paise = Decimal(str(raw))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0.00")
    if paise < 0:
        return Decimal("0.00")
    return (paise / Decimal(100)).quantize(Decimal("0.01"))


def payment_link_case_ref(payload: dict[str, Any]) -> str | None:
    """A Torque-set case reference on the link (`notes.torque_case_id`, or
    `reference_id`) — present only for links Torque generated. `None` for an
    externally-created link."""
    entity = payment_link_entity(payload)
    notes = entity.get("notes")
    if isinstance(notes, dict):
        for key in ("torque_case_id", "case_id"):
            v = notes.get(key)
            if v:
                return str(v)
    ref = entity.get("reference_id")
    return str(ref) if ref else None


def _customer(payload: dict[str, Any]) -> dict[str, Any]:
    cust = payment_link_entity(payload).get("customer")
    return cust if isinstance(cust, dict) else {}


def payment_link_contact_phone(payload: dict[str, Any]) -> str | None:
    return _customer(payload).get("contact") or None


def payment_link_contact_email(payload: dict[str, Any]) -> str | None:
    return _customer(payload).get("email") or None
