"""Phase 0 §0.6 — the AI feature flag defaults to disabled and requires no
environment configuration to import cleanly (AI must be addable without
disrupting anyone's existing dev setup)."""

from __future__ import annotations


def test_ai_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TORQUE_AI_ENABLED", raising=False)
    from torque.ai.config import AISettings

    assert AISettings().enabled is False


def test_ai_enabled_via_env(monkeypatch):
    monkeypatch.setenv("TORQUE_AI_ENABLED", "true")
    from torque.ai.config import AISettings

    assert AISettings().enabled is True


def test_get_ai_settings_is_cached_like_get_settings(monkeypatch):
    """Same `lru_cache` pattern as `torque.config.get_settings` /
    `get_policy` — a sanity check that the convention was actually followed,
    not just described in a docstring."""
    from torque.ai.config import get_ai_settings

    assert get_ai_settings() is get_ai_settings()
