"""Module 11 — liveness / readiness and the app-wiring contract.

`/health` behaviour is unchanged (Milestone 7a). `/health/ready` reports whether
the API can reach PostgreSQL and the Redis broker; the two probe functions are
substituted so this test needs neither a live Redis nor a specific DB state.
"""

from __future__ import annotations

import pytest

from torque.api import health


@pytest.fixture()
def client(make_api_client):
    return make_api_client()


def test_health_liveness_unchanged(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_ok_when_infra_reachable(client, monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database", lambda: (True, "ok"))
    monkeypatch.setattr(health, "check_redis", lambda url: (True, "ok"))
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


def test_ready_503_when_database_unreachable(client, monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database", lambda: (False, "OperationalError: down"))
    monkeypatch.setattr(health, "check_redis", lambda url: (True, "ok"))
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not ready"
    assert body["checks"]["database"] == "OperationalError: down"
    assert body["checks"]["redis"] == "ok"


def test_ready_503_when_redis_unreachable(client, monkeypatch) -> None:
    monkeypatch.setattr(health, "check_database", lambda: (True, "ok"))
    monkeypatch.setattr(health, "check_redis", lambda url: (False, "ConnectionError: refused"))
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] == "ConnectionError: refused"


def test_real_probes_have_the_expected_shape(client) -> None:
    # check_database actually runs against the test DB (up during the suite).
    ok, detail = health.check_database()
    assert ok is True and detail == "ok"
    # check_redis against a dead port fails closed, fast, without raising.
    ok, detail = health.check_redis("redis://127.0.0.1:1/0")
    assert ok is False and isinstance(detail, str) and detail


def test_core_surfaces_still_wired(client) -> None:
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {"/health", "/health/ready"} <= paths
    for prefix in ("/webhooks/", "/internal/", "/reports/", "/agent-console/", "/demo/"):
        assert any(p.startswith(prefix) for p in paths), prefix
    # `/` redirects to the mounted static UI, which serves index.html.
    root = client.get("/", follow_redirects=False)
    assert root.status_code in (302, 307)
    assert root.headers["location"].endswith("/ui/")
    assert client.get("/ui/").status_code == 200
