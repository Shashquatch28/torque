"""The FastAPI application factory.

`create_app()` builds the app with its routes and nothing else — no startup DB
work, no background tasks. Milestone 7a's surface is exactly two routes:

* `GET  /health`                       — liveness for the runner / preview env.
* `POST /webhooks/razorpay/{merchant_id}` — the Razorpay webhook (see webhooks.py).
"""

from __future__ import annotations

from fastapi import FastAPI

from torque.api.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="Torque", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(webhooks_router)
    return app
