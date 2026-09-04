"""The FastAPI application factory.

`create_app()` builds the app with its routes and nothing else — no startup DB
work, no background tasks. Surfaces:

* `GET  /health`                              — liveness for the runner / preview.
* `GET  /health/ready`                        — readiness: the API can reach
  PostgreSQL + the Redis broker (Module 11) — see `health.py`.
* `POST /webhooks/razorpay/{merchant_id}`     — the Razorpay webhook (Legs 1, 3,
  4 + the success signals) — see `webhooks.py`.
* `POST /internal/checkout-abandoned/{merchant_id}` — the signed synthetic
  `checkout.abandoned` injection (Leg 2, §2.6) — see `checkout_injection.py`.
* `GET  /reports/{merchant_id}/...`           — Module 9/10 read-only reporting
  (recovery report, top-at-risk, human queue, activity feed) — see `reporting.py`.
* `POST /agent-console/{merchant_id}/...`     — Module 10 human overrides
  (resolve / pause / unpause) — see `agent_console.py`.
* `GET  /ai/{merchant_id}/cases/{case_id}/explain` — Phase 6 read-only AI case
  narrative (citation-grounded, `TORQUE_AI_ENABLED`-gated) — see `ai.py`.
* `POST /demo/...` , `GET /demo/...`          — Module 10 Demo Surface controls
  (seed + one-click synthetic scenarios) — see `demo.py`.
* `GET  /` , `/ui/`                           — the Module 10 static UI shell —
  see `ui.py`. Served by this same process on this same port.
"""

from __future__ import annotations

from fastapi import FastAPI

from torque.api.agent_console import router as agent_console_router
from torque.api.ai import router as ai_router
from torque.api.checkout_injection import router as checkout_injection_router
from torque.api.demo import router as demo_router
from torque.api.health import router as health_router
from torque.api.reporting import router as reporting_router
from torque.api.ui import mount_ui
from torque.api.ui import router as ui_router
from torque.api.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="Torque", version="0.1.0")

    app.include_router(health_router)
    app.include_router(webhooks_router)
    app.include_router(checkout_injection_router)
    app.include_router(reporting_router)
    app.include_router(agent_console_router)
    app.include_router(ai_router)
    app.include_router(demo_router)
    app.include_router(ui_router)
    mount_ui(app)
    return app
