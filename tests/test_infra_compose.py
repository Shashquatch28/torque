"""Module 11 — the docker-compose / Dockerfile runtime contract.

Parses the infra files (no Docker required) and asserts they reproduce the
runtime the code expects: db + redis + migrate + api + worker + beat, Redis as
broker-only, host ports preserved, no Temporal / Kubernetes / monitoring stack.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"

APP_SERVICES = ("migrate", "api", "worker", "beat")


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def services(compose: dict) -> dict:
    return compose["services"]


def test_all_five_runtime_services_defined(services: dict) -> None:
    assert set(services) == {"db", "redis", "migrate", "api", "worker", "beat"}


def test_infra_services_start_by_default_app_services_are_profiled(services: dict) -> None:
    # A bare `docker compose up` must still bring only the infrastructure.
    assert "profiles" not in services["db"]
    assert "profiles" not in services["redis"]
    for name in APP_SERVICES:
        assert services[name].get("profiles") == ["full"], name


def test_postgres_service(services: dict) -> None:
    db = services["db"]
    assert db["image"].startswith("postgres:")
    assert "5442:5432" in db["ports"]
    assert "healthcheck" in db
    assert "torque_pgdata:/var/lib/postgresql/data" in db["volumes"]


def test_redis_is_broker_only_no_persistence(services: dict) -> None:
    redis = services["redis"]
    assert redis["image"].startswith("redis:")
    assert "6389:6379" in redis["ports"]
    assert "healthcheck" in redis
    # Broker transport only — nothing durable is kept in Redis.
    assert "volumes" not in redis
    raw = COMPOSE_PATH.read_text(encoding="utf-8").lower()
    assert "appendonly" not in raw
    assert "--save" not in raw


def test_app_services_share_one_build(services: dict) -> None:
    for name in APP_SERVICES:
        build = services[name]["build"]
        assert build["context"] == "."
        assert build["dockerfile"] == "Dockerfile"
        assert services[name]["image"] == "torque-app:local"


def test_app_services_point_at_compose_network_infra(services: dict) -> None:
    for name in APP_SERVICES:
        env = services[name]["environment"]
        assert "@db:5432/torque" in env["DATABASE_URL"], name
        assert env["REDIS_URL"] == "redis://redis:6379/0", name


def test_api_service(services: dict) -> None:
    api = services["api"]
    assert api["command"] == ["python", "-m", "torque"]
    assert "8000:8000" in api["ports"]
    assert api["environment"]["TORQUE_API_HOST"] == "0.0.0.0"
    dep = api["depends_on"]
    assert dep["db"]["condition"] == "service_healthy"
    assert dep["redis"]["condition"] == "service_healthy"
    assert dep["migrate"]["condition"] == "service_completed_successfully"
    # readiness-gated
    assert "health" in " ".join(api["healthcheck"]["test"]).lower()


def test_migrate_service_is_one_shot_schema_upgrade(services: dict) -> None:
    migrate = services["migrate"]
    assert migrate["command"] == ["alembic", "upgrade", "head"]
    assert migrate["restart"] == "no"
    assert migrate["depends_on"]["db"]["condition"] == "service_healthy"


def test_worker_service_runs_the_celery_worker(services: dict) -> None:
    cmd = services["worker"]["command"]
    assert "worker" in cmd
    assert "torque.ingestion.celery_app:celery_app" in cmd
    dep = services["worker"]["depends_on"]
    assert dep["redis"]["condition"] == "service_healthy"
    assert dep["migrate"]["condition"] == "service_completed_successfully"


def test_beat_service_runs_the_celery_beat_trigger(services: dict) -> None:
    cmd = services["beat"]["command"]
    assert "beat" in cmd
    assert "torque.ingestion.celery_app:celery_app" in cmd
    # non-root container: the schedule bookkeeping file goes somewhere writable.
    assert any(str(part).startswith("--schedule=") for part in cmd)
    dep = services["beat"]["depends_on"]
    assert dep["migrate"]["condition"] == "service_completed_successfully"


def test_no_temporal_no_k8s_no_monitoring_stack() -> None:
    raw = COMPOSE_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("temporal", "kubernetes", "prometheus", "grafana", "kibana", "jaeger"):
        assert forbidden not in raw, forbidden


def test_dockerfile_single_reusable_image_non_root_locked_deps() -> None:
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "FROM python:3.11-slim" in text
    assert "USER torque" in text  # non-root
    assert "uv sync --frozen" in text  # lockfile-reproducible
    assert "temporal" not in text.lower()
    # one CMD (the API); worker/beat override via compose command
    assert text.count("\nCMD ") + text.startswith("CMD ") == 1


def test_dockerignore_present_and_trims_context() -> None:
    text = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
    assert ".git/" in text
    assert ".env" in text
    assert "tests/" in text


def test_pyproject_has_no_temporal_dependency() -> None:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "temporal" not in text
