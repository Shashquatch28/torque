"""The FastAPI application factory.

`create_app()` builds the app with its routes and nothing else — no startup DB
work, no background tasks. The Module 2 HTTP surface:

* `GET  /health`                              — liveness for the runner / preview.
* `POST /webhooks/razorpay/{merchant_id}`     — the Razorpay webhook (Legs 1, 3,
  4 + the success signals) — see `webhooks.py`.
* `POST /internal/checkout-abandoned/{merchant_id}` — the signed synthetic
  `checkout.abandoned` injection (Leg 2, §2.6) — see `checkout_injection.py`.
"""

from __future__ import annotations

from fastapi import FastAPI

from torque.api.checkout_injection import router as checkout_injection_router
from torque.api.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="Torque", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(webhooks_router)
    app.include_router(checkout_injection_router)
    return app
