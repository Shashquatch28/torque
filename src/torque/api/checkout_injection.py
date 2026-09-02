"""Signed synthetic `checkout.abandoned` injection — Blueprint §2.6 / Part D item 1.

There is no Razorpay webhook for checkout abandonment. The demo-scope path (the
confirmed default) is a signed internal endpoint. It mirrors the Razorpay webhook
(`torque.api.webhooks`, INV-23) exactly:

1. read the raw body, HMAC-SHA256 verify it (constant-time) against
   `Settings.checkout_injection_secret` — the §2.2 pattern with a dedicated
   secret; missing/unset secret or bad signature → empty HTTP 200, no `Event`;
2. parse; extract `X-Torque-Event-Id` (header-sourced idempotency key, **never**
   payload-derived — §2.5); already-seen → 200, no reprocess;
3. unknown `{merchant_id}` → 200, no `Event`;
4. else write one `Event(type="checkout.abandoned")` via `TenantScope` and
   enqueue `create_checkout_case_task` (no buffer — §2.3).

A real storefront SDK/pixel is a separate build item (Part D item 1) and is not
built here.
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
from torque.ingestion.checkout import CHECKOUT_ABANDONED
from torque.ingestion.tasks import create_checkout_case_task
from torque.models import Event, Merchant
from torque.security.razorpay_signature import verify_razorpay_signature

router = APIRouter()

SIGNATURE_HEADER = "X-Torque-Signature"
EVENT_ID_HEADER = "X-Torque-Event-Id"


def _ok() -> Response:
    return Response(status_code=200)


@router.post("/internal/checkout-abandoned/{merchant_id}")
async def checkout_abandoned(
    merchant_id: str,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    raw_body = await request.body()

    secret = settings.checkout_injection_secret
    signature = request.headers.get(SIGNATURE_HEADER)
    if not secret or not verify_razorpay_signature(raw_body, signature, secret):
        return _ok()

    try:
        payload = json.loads(raw_body)
    except ValueError:
        return _ok()
    if not isinstance(payload, dict):
        return _ok()

    event_id = request.headers.get(EVENT_ID_HEADER)
    if not event_id:
        return _ok()

    if session.get(Merchant, merchant_id) is None:
        return _ok()

    already = session.scalar(
        select(Event.event_id).where(Event.idempotency_key == event_id)
    )
    if already is not None:
        return _ok()

    event = Event(
        type=str(payload.get("event") or CHECKOUT_ABANDONED),
        idempotency_key=event_id,
        raw_payload=payload,
        processed=False,
    )
    TenantScope(session, merchant_id).add(event)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return _ok()

    create_checkout_case_task.apply_async((str(event.event_id),))
    return _ok()
