"""Razorpay webhook ingestion — Blueprint Module 2 §2.2 (Milestone 7a).

The verify-before-parse pipeline, exactly as specified:

1. Read the raw request body — do not parse yet.
2. Select the single webhook secret for this deployment's mode (never try both).
3. HMAC-SHA256 the raw bytes, constant-time compare against `X-Razorpay-Signature`.
4. Missing secret / missing header / mismatch  -> HTTP 200, drop silently. No
   `Event` row, no `CaseEvent`, no side effect of any kind. (200 rather than 4xx
   so Razorpay does not enter retry-on-failure for a request that will never
   verify.)
5. Match -> parse the body, read `X-Razorpay-Event-Id`.
6. `Event.idempotency_key` (= that header) already present -> HTTP 200, no
   reprocessing.
7. New -> write exactly one `Event` row (`processed = False`) through the
   tenancy facade, keyed to the `{merchant_id}` in the path.

Everything after step 7 in the blueprint's dispatch summary — the self-recovery
buffer, cross-leg dedup, systemic hold, retry-budget seeding, dispatch to
Module 3 — is a later sub-milestone. M7a stops at a verified, deduplicated
`Event`.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from torque.api.deps import get_db
from torque.config import Settings, get_settings
from torque.db.scoped import TenantScope
from torque.ingestion.b2b import INVOICE_OVERDUE
from torque.ingestion.buffer import PAYMENT_FAILED, payment_failure_buffer_seconds
from torque.ingestion.subscription import (
    SUBSCRIPTION_FAILED,
    subscription_failure_buffer_seconds,
)
from torque.ingestion.tasks import (
    ingest_invoice_task,
    resolve_buffered_event_task,
    resolve_subscription_buffered_event_task,
)
from torque.models import Event, Merchant
from torque.reconciliation.reconcile import RECONCILE_EVENT_TYPES
from torque.reconciliation.tasks import reconcile_event_task
from torque.security.razorpay_signature import verify_razorpay_signature

router = APIRouter()

SIGNATURE_HEADER = "X-Razorpay-Signature"
EVENT_ID_HEADER = "X-Razorpay-Event-Id"

# A verified event whose body carries no top-level `event` field is still a
# real, authenticated signal and is persisted (the table is the raw inbound
# log); it is recorded under this sentinel type rather than dropped.
UNKNOWN_EVENT_TYPE = "unknown"


def _ok() -> Response:
    """An empty HTTP 200 — the only response this endpoint ever gives, whether
    it accepted, deduplicated, or silently dropped the request. Razorpay only
    inspects the status code."""
    return Response(status_code=200)


@router.post("/webhooks/razorpay/{merchant_id}")
async def razorpay_webhook(
    merchant_id: str,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    raw_body = await request.body()

    # --- verify BEFORE parsing (steps 1-4) --------------------------------
    secret = settings.active_razorpay_webhook_secret()
    signature = request.headers.get(SIGNATURE_HEADER)
    if not secret or not verify_razorpay_signature(raw_body, signature, secret):
        return _ok()

    # --- safe to parse now (step 5) -------------------------------------
    try:
        payload = json.loads(raw_body)
    except ValueError:
        # Authenticated, but not JSON — nothing to persist without a shape.
        return _ok()
    if not isinstance(payload, dict):
        return _ok()

    event_id = request.headers.get(EVENT_ID_HEADER)
    if not event_id:
        # Idempotency key is sourced from the header only, never payload-derived
        # (Blueprint 2.5). Without it we cannot dedup — drop.
        return _ok()

    # The path names the merchant whose Razorpay account posted this. If it is
    # not a merchant we know, there is nothing to attribute the Event to.
    if session.get(Merchant, merchant_id) is None:
        return _ok()

    # --- idempotency (step 6) -----------------------------------------
    already = session.scalar(
        select(Event.event_id).where(Event.idempotency_key == event_id)
    )
    if already is not None:
        return _ok()

    # --- write one Event row through the tenancy facade (step 7) --------
    event = Event(
        type=str(payload.get("event") or UNKNOWN_EVENT_TYPE),
        idempotency_key=event_id,
        raw_payload=payload,
        processed=False,
    )
    scope = TenantScope(session, merchant_id)
    scope.add(event)
    try:
        session.flush()
    except IntegrityError:
        # A concurrent request inserted the same idempotency_key between our
        # SELECT and this flush. Ingestion is idempotent — treat as done.
        session.rollback()
        return _ok()

    # Blueprint §2.3: a failure case is NOT created synchronously — the verified
    # Event is handed to a Celery self-recovery buffer (90 s for `payment.failed`,
    # 30 s for `subscription.charged.failed`). Success events (`payment.captured`,
    # `subscription.charged`) are persisted and read later by the buffers; other
    # types are persisted and await a future leg's milestone.
    if event.type == PAYMENT_FAILED:
        resolve_buffered_event_task.apply_async(
            (str(event.event_id),),
            countdown=payment_failure_buffer_seconds(),
        )
    elif event.type == SUBSCRIPTION_FAILED:
        resolve_subscription_buffered_event_task.apply_async(
            (str(event.event_id),),
            countdown=subscription_failure_buffer_seconds(),
        )
    elif event.type == INVOICE_OVERDUE:
        # §2.3: `invoice.overdue` needs no buffer — dispatch immediately.
        ingest_invoice_task.apply_async((str(event.event_id),))
    elif event.type in RECONCILE_EVENT_TYPES:
        # Module 7 §7.3 — a verified success signal (`payment.captured`,
        # `subscription.charged`, `payment_link.paid` / `.partially_paid` /
        # `.expired` / `.cancelled`) is handed to reconciliation. No buffer: the
        # engine is correct whenever it runs (no case yet → NO_MATCH; a case
        # present → recover / cancel), and it is idempotent on `Event.processed`.
        reconcile_event_task.apply_async((str(event.event_id),))

    return _ok()
