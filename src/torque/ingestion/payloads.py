"""Pure extractors over a Razorpay `payment.*` / `subscription.*` webhook payload.

Side-effect-free, no DB. Every function tolerates a missing key and returns
`None` / a safe default rather than raising — a verified-but-thin payload still
produces a (sparse) case rather than a 500.

Razorpay `payment.failed` / `payment.captured` body (the parts Leg 1 reads):

    { "event": "payment.failed",
      "payload": { "payment": { "entity": {
          "id": "pay_...", "order_id": "order_...", "amount": 49900,
          "method": "card", "email": "...", "contact": "+91...",
          "token_id": "token_...", "card_id": "card_...",
          "error_code": "BAD_REQUEST_ERROR", "error_reason": "payment_failed",
      } } } }

Razorpay `subscription.charged.failed` / `subscription.charged` body carries BOTH
a `payment` entity (as above, plus `method` = `upi` | `card` | `emandate` | …)
and a `subscription` entity (the parts Leg 3 reads):

    { "event": "subscription.charged.failed",
      "payload": {
        "payment":      { "entity": { … "method": "upi", "token_id": "token_…" } },
        "subscription": { "entity": { "id": "sub_…", "paid_count": 4, … } } } }

`amount` is in paise; `amount_rupees` converts to a 2dp `Decimal`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from torque.enums import MandateType, PaymentMethodAttempted


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


# --- subscription (Leg 3) --------------------------------------------------

_METHOD_TO_MANDATE = {
    "upi": MandateType.UPI_AUTOPAY,
    "card": MandateType.CARD,
    "emandate": MandateType.NACH,
    "nach": MandateType.NACH,
    "netbanking": MandateType.NACH,
}


def subscription_entity(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        entity = payload["payload"]["subscription"]["entity"]
    except (KeyError, TypeError):
        return {}
    return entity if isinstance(entity, dict) else {}


def subscription_id(payload: dict[str, Any]) -> str | None:
    v = subscription_entity(payload).get("id")
    return v or None


def mandate_id(payload: dict[str, Any]) -> str | None:
    """The recurring-mandate identifier — Razorpay's `payment.entity.token_id`,
    its canonical handle for the authorised mandate (a UPI mandate token for UPI
    AutoPay, a bank e-mandate token for NACH, a card-on-file token for CARD
    recurring). Returns `None` when the payload carries no token.

    A `subscription.id` is **not** a mandate id — the blueprint keeps
    `mandate_id` and `subscription_id` as distinct `SubscriptionFailureContext`
    fields, and `UPIRetryBudget` is "scoped per-mandate" (Part A §3). It is never
    substituted; a signal with no token seeds no `UPIRetryBudget` /
    `NACHRetryPolicy`, exactly as a card payment with no instrument reference
    seeds no `CardRetryBudget` (D-069 / D-072)."""
    return payment_entity(payload).get("token_id") or None


def billing_cycle(payload: dict[str, Any]) -> str:
    """A short free-string label for the cycle that failed. Razorpay gives no
    `billing_cycle` field — this is the 1-based ordinal derived from
    `subscription.entity.paid_count` (successful charges so far)."""
    paid = subscription_entity(payload).get("paid_count")
    try:
        return str(int(paid) + 1)
    except (TypeError, ValueError):
        return "1"


def mandate_type_from_method(method: str | None) -> MandateType:
    """Map the Razorpay `payment.entity.method` of a failed subscription charge to
    Torque's `MandateType`. Unknown / missing → `NACH` — the conservative
    bank-debit default (clearing-cycle aware, self-imposed ceiling). See D-070."""
    return _METHOD_TO_MANDATE.get((method or "").lower(), MandateType.NACH)


def subscription_failure_context(payload: dict[str, Any]) -> dict[str, Any]:
    """The ingestion-time `SubscriptionFailureContext` dict. All four fields are
    required by the model; a thin payload yields empty strings for the ids (a
    sparse case, not a 500 — rail-budget seeding is then skipped)."""
    return {
        "mandate_id": mandate_id(payload) or "",
        "mandate_type": mandate_type_from_method(payment_method(payload)),
        "billing_cycle": billing_cycle(payload),
        "subscription_id": subscription_id(payload) or "",
    }


# --- checkout abandonment (Leg 2) ---------------------------------------

_CHECKOUT_METHODS = {m.value for m in PaymentMethodAttempted}


def checkout_entity(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        entity = payload["payload"]["checkout"]["entity"]
    except (KeyError, TypeError):
        return {}
    return entity if isinstance(entity, dict) else {}


def checkout_cart_id(payload: dict[str, Any]) -> str | None:
    return checkout_entity(payload).get("cart_id") or None


def checkout_drop_stage(payload: dict[str, Any]) -> str:
    return str(checkout_entity(payload).get("drop_stage") or "unknown")


def checkout_payment_method(payload: dict[str, Any]) -> str:
    """The `CheckoutAbandonmentContext.payment_method_attempted` value from the
    §4 vocabulary (`UPI_COLLECT | UPI_INTENT | CARD | NETBANKING | BNPL | NONE`).
    Anything unrecognised → `NONE`."""
    raw = str(checkout_entity(payload).get("payment_method_attempted") or "").upper()
    return raw if raw in _CHECKOUT_METHODS else PaymentMethodAttempted.NONE.value


def checkout_cart_value_rupees(payload: dict[str, Any]) -> Decimal:
    raw = checkout_entity(payload).get("cart_value")
    try:
        paise = Decimal(str(raw))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0.00")
    if paise < 0:
        return Decimal("0.00")
    return (paise / Decimal(100)).quantize(Decimal("0.01"))


def checkout_contact_phone(payload: dict[str, Any]) -> str | None:
    return checkout_entity(payload).get("contact") or None


def checkout_contact_email(payload: dict[str, Any]) -> str | None:
    return checkout_entity(payload).get("email") or None


def checkout_abandonment_context(payload: dict[str, Any]) -> dict[str, Any]:
    """The ingestion-time `CheckoutAbandonmentContext` dict. All four fields are
    required by the model; a thin payload yields safe defaults (empty `cart_id`,
    `0.00` value, `unknown` stage, `NONE` method) — a sparse case, not a 500."""
    return {
        "cart_id": checkout_cart_id(payload) or "",
        "cart_value": checkout_cart_value_rupees(payload),
        "drop_stage": checkout_drop_stage(payload),
        "payment_method_attempted": checkout_payment_method(payload),
    }


# --- B2B invoice (Leg 4) ----------------------------------------------

def invoice_entity(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        entity = payload["payload"]["invoice"]["entity"]
    except (KeyError, TypeError):
        return {}
    return entity if isinstance(entity, dict) else {}


def _paise_to_rupees(raw: Any) -> Decimal | None:
    try:
        paise = Decimal(str(raw))
    except (TypeError, ValueError, ArithmeticError):
        return None
    return (paise / Decimal(100)).quantize(Decimal("0.01"))


def invoice_original_rupees(payload: dict[str, Any]) -> Decimal:
    v = _paise_to_rupees(invoice_entity(payload).get("amount"))
    return v if v is not None and v >= 0 else Decimal("0.00")


def invoice_outstanding_rupees(payload: dict[str, Any], original: Decimal) -> Decimal:
    """`amount_due` (paise) → ₹, clamped to `[0, original]` to satisfy the
    `B2BInvoice` CHECK constraints. Falls back to `amount - amount_paid`, then to
    `original`."""
    entity = invoice_entity(payload)
    due = _paise_to_rupees(entity.get("amount_due"))
    if due is None:
        paid = _paise_to_rupees(entity.get("amount_paid")) or Decimal("0.00")
        due = original - paid
    if due < 0:
        due = Decimal("0.00")
    if due > original:
        due = original
    return due


def invoice_due_date(payload: dict[str, Any]) -> date | None:
    entity = invoice_entity(payload)
    for key in ("expire_by", "due_date", "date"):
        ts = entity.get(key)
        if ts:
            try:
                return datetime.fromtimestamp(int(ts), tz=UTC).date()
            except (TypeError, ValueError, OSError, OverflowError):
                continue
    return None


def invoice_gst_inclusive(payload: dict[str, Any]) -> bool:
    entity = invoice_entity(payload)
    return bool(entity.get("gst")) or bool(entity.get("tax_amount"))


def invoice_payment_terms(payload: dict[str, Any]) -> str | None:
    v = invoice_entity(payload).get("terms")
    return str(v)[:64] or None if v else None


def _invoice_customer(payload: dict[str, Any]) -> dict[str, Any]:
    cd = invoice_entity(payload).get("customer_details")
    return cd if isinstance(cd, dict) else {}


def invoice_contact_phone(payload: dict[str, Any]) -> str | None:
    return _invoice_customer(payload).get("contact") or None


def invoice_contact_email(payload: dict[str, Any]) -> str | None:
    return _invoice_customer(payload).get("email") or None
