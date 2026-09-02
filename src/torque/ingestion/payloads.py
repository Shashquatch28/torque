"""Pure extractors over a Razorpay `payment.*` webhook payload.

Side-effect-free, no DB. Every function tolerates a missing key and returns
`None` / a safe default rather than raising — a verified-but-thin payload still
produces a (sparse) case rather than a 500.

Razorpay `payment.failed` / `payment.captured` body shape (the parts M7b reads):

    { "event": "payment.failed",
      "payload": { "payment": { "entity": {
          "id": "pay_...", "order_id": "order_...", "amount": 49900,
          "method": "card", "email": "...", "contact": "+91...",
          "token_id": "token_...", "card_id": "card_...",
          "error_code": "BAD_REQUEST_ERROR", "error_reason": "payment_failed",
      } } } }

`amount` is in paise; `amount_rupees` converts to a 2dp `Decimal`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def payment_entity(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        entity = payload["payload"]["payment"]["entity"]
    except (KeyError, TypeError):
        return {}
    return entity if isinstance(entity, dict) else {}


def payment_id(payload: dict[str, Any]) -> str | None:
    v = payment_entity(payload).get("id")
    return v or None


def order_id(payload: dict[str, Any]) -> str | None:
    v = payment_entity(payload).get("order_id")
    return v or None


def contact_phone(payload: dict[str, Any]) -> str | None:
    v = payment_entity(payload).get("contact")
    return v or None


def contact_email(payload: dict[str, Any]) -> str | None:
    v = payment_entity(payload).get("email")
    return v or None


def payment_method(payload: dict[str, Any]) -> str | None:
    v = payment_entity(payload).get("method")
    return v or None


def is_card_payment(payload: dict[str, Any]) -> bool:
    return payment_method(payload) == "card"


def card_instrument_ref(payload: dict[str, Any]) -> str | None:
    """`COALESCE(token_id, card_id)` — the Razorpay tokenised card reference that
    the webhook payload provides. **Torque never receives or stores a PAN.**

    M7b writes this value into the existing `CardRetryBudget.card_token_hash`
    column. That column name is inherited from the Module-1 schema and is NOT
    renamed here; M7b performs NO hashing. A keyed-HMAC / pepper representation
    of the instrument key is a future security-hardening item, out of M7b scope.
    """
    entity = payment_entity(payload)
    return entity.get("token_id") or entity.get("card_id") or None


def amount_rupees(payload: dict[str, Any]) -> Decimal:
    raw = payment_entity(payload).get("amount")
    try:
        paise = Decimal(str(raw))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0.00")
    if paise < 0:
        return Decimal("0.00")
    return (paise / Decimal(100)).quantize(Decimal("0.01"))


def payment_degradation_context(payload: dict[str, Any]) -> dict[str, Any]:
    """The ingestion-time `PaymentDegradationContext` dict.

    `decline_code` is the raw Razorpay `error_code`, verbatim (or `None`).
    Ingestion does NOT read `error_reason` / `error_source` / `error_step` and
    runs no classifier. `is_hard_decline` is deliberately omitted → the model
    default `None` ("not yet classified"); the Diagnosis Engine (Module 3) owns
    the hard/soft verdict (Blueprint Part C item 4 / §3.1; D-058).
    """
    return {
        "gateway": "razorpay",
        "decline_code": payment_entity(payload).get("error_code") or None,
        "retry_count": 0,
    }
