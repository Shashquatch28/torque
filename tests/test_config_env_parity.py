"""Module 11 — configuration coherence.

`.env.example` documents the whole `Settings` + `PolicyConfig` surface, carries
no real secrets, and the defaults fail closed (no webhook secret ⇒ verification
cannot pass; Celery is not eager).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import AliasChoices

from torque.config import PolicyConfig, Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"

POLICY_PREFIX = "TORQUE_POLICY_"
# Keys read directly by the test harness / alembic env, not Settings fields.
HARNESS_ONLY = {"TORQUE_TEST_ADMIN_URL", "TORQUE_ALEMBIC_URL"}


def _parse_env_example() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _accepted_env_names(field_name: str, field) -> set[str]:
    names = {field_name.upper()}
    alias = getattr(field, "validation_alias", None)
    if isinstance(alias, str):
        names.add(alias.upper())
    elif isinstance(alias, AliasChoices):
        names.update(str(c).upper() for c in alias.choices if isinstance(c, str))
    return names


@pytest.fixture(scope="module")
def env() -> dict[str, str]:
    return _parse_env_example()


def test_every_settings_field_is_documented(env: dict[str, str]) -> None:
    for name, field in Settings.model_fields.items():
        accepted = _accepted_env_names(name, field)
        assert accepted & set(env), f"Settings.{name} not in .env.example (any of {accepted})"


def test_every_policy_field_is_documented(env: dict[str, str]) -> None:
    for name in PolicyConfig.model_fields:
        key = f"{POLICY_PREFIX}{name.upper()}"
        assert key in env, f"{key} missing from .env.example"


def test_no_unknown_keys_in_env_example(env: dict[str, str]) -> None:
    allowed: set[str] = set(HARNESS_ONLY)
    for name, field in Settings.model_fields.items():
        allowed |= _accepted_env_names(name, field)
    allowed |= {f"{POLICY_PREFIX}{n.upper()}" for n in PolicyConfig.model_fields}
    unknown = set(env) - allowed
    assert not unknown, f".env.example has keys unknown to Settings/PolicyConfig: {unknown}"


def test_no_real_secrets_committed(env: dict[str, str]) -> None:
    for key, value in env.items():
        if "SECRET" in key:
            assert value == "", f"{key} must be blank in .env.example"


def test_defaults_fail_closed() -> None:
    s = Settings(_env_file=None)
    # No webhook secret configured ⇒ the endpoint cannot verify anything.
    assert s.active_razorpay_webhook_secret() is None
    assert s.razorpay_webhook_secret_live is None
    assert s.razorpay_webhook_secret_test is None
    assert s.checkout_injection_secret is None
    # Celery is never eager outside the test harness.
    assert s.celery_task_always_eager is False
    # Sensible local defaults.
    assert s.api_host == "127.0.0.1"
    assert s.api_port == 8000
    assert s.redis_url.startswith("redis://")
    assert s.database_url.startswith("postgresql+psycopg://")


def test_api_bind_env_vars_are_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TORQUE_API_HOST", "0.0.0.0")
    monkeypatch.setenv("TORQUE_API_PORT", "9001")
    s = Settings(_env_file=None)
    assert s.api_host == "0.0.0.0"
    assert s.api_port == 9001
