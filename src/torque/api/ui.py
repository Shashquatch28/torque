"""Module 10 — the UI shell (Blueprint §10).

A single self-contained static app (`ui/static/index.html` + `torque.css` +
`torque.js`) mounted at `/ui`, served by the **same** uvicorn process on the
**same** port as the JSON API. No Node, no build step, no second server — the
whole product runs with `uv run python -m torque`.

The app is a hash-router SPA (`#/dashboard`, `#/cases`, `#/cases/<id>`,
`#/console`, `#/demo`). It holds a `merchant_id` in client state and calls only
tenant-scoped backend endpoints (`/reports/{merchant_id}/…`,
`/agent-console/{merchant_id}/…`) — never a cross-merchant path, and it never
computes a metric or a ranking itself.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent.parent / "ui" / "static"

router = APIRouter()


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


def mount_ui(app) -> None:
    """Attach the static UI to `app` at `/ui` (called from `create_app`)."""
    app.mount(
        "/ui",
        StaticFiles(directory=str(STATIC_DIR), html=True),
        name="ui",
    )
