"""Liveness and readiness (Module 11 — Tech Stack & Infra).

* ``GET /health``       — liveness. Static, no I/O. The process is up. Behaviour
  unchanged from Milestone 7a.
* ``GET /health/ready`` — readiness. Cheap probes that the API can actually
  reach its required infrastructure: ``SELECT 1`` against PostgreSQL and
  ``PING`` against the Redis broker. ``200`` when both answer; ``503`` (naming
  the failed component) otherwise.

Deliberately minimal — no metrics, no tracing, no dependency graph. Just enough
for a human or ``docker compose`` to tell the API is wired to its infra. The
two check functions are module-level so tests can substitute them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from torque.config import Settings, get_settings

router = APIRouter(tags=["health"])

_PROBE_TIMEOUT_SECONDS = 1.0


def check_database() -> tuple[bool, str]:
    """``SELECT 1`` on a short-lived session. ``(True, "ok")`` iff Postgres answers."""
    from torque.db.session import SessionLocal

    try:
        session = SessionLocal()
        try:
            session.execute(text("SELECT 1"))
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 — a probe reports, it never raises
        return False, f"{type(exc).__name__}: {exc}"
    return True, "ok"


def check_redis(redis_url: str) -> tuple[bool, str]:
    """``PING`` the Celery broker. ``(True, "ok")`` iff Redis answers."""
    try:
        import redis

        client = redis.from_url(
            redis_url,
            socket_connect_timeout=_PROBE_TIMEOUT_SECONDS,
            socket_timeout=_PROBE_TIMEOUT_SECONDS,
        )
        try:
            client.ping()
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, "ok"


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness — the process is up. No I/O."""
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Readiness — the API can reach PostgreSQL and the Redis broker."""
    db_ok, db_detail = check_database()
    redis_ok, redis_detail = check_redis(settings.redis_url)
    ready = db_ok and redis_ok
    body = {
        "status": "ready" if ready else "not ready",
        "checks": {"database": db_detail, "redis": redis_detail},
    }
    return JSONResponse(body, status_code=200 if ready else 503)
