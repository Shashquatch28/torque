"""Runtime configuration and policy values.

Blueprint v7 is explicit (Decision E, Part E items 9-12) that tunable windows
and thresholds are *policy values*, not hardcoded literals. This module is their
single home. Milestone 1 does not consume the policy values below — they are
declared here so that Modules 2, 3, 7, and 8 have a defined place to read them
from instead of scattering magic numbers through the codebase.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Port 5442: the docker-compose db publishes there to avoid colliding with a
    # local Postgres on the standard 5432. Override via .env for other setups.
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5442/torque"
    )
    test_database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5442/torque_test"
    )

    # Razorpay dashboard-set secrets. Live and Test are distinct and must never
    # be crossed (Blueprint Section 2.5 / Decision L). Consumed by Module 2.
    razorpay_webhook_secret_live: str | None = None
    razorpay_webhook_secret_test: str | None = None


class PolicyConfig(BaseSettings):
    """Tunable operational values. Stated defaults from Blueprint Part E.

    None of these are consumed in Milestone 1. They are enumerated so later
    modules read `PolicyConfig` fields rather than embedding literals.
    """

    model_config = SettingsConfigDict(env_prefix="TORQUE_POLICY_", extra="ignore")

    # Module 2 Section 2.3 — self-recovery buffer windows (Part E item 9).
    payment_failure_buffer_seconds: int = 90
    subscription_failure_buffer_seconds: int = 30
    # Module 2 Section 2.4 — cross-leg dedup lookback (Part E item 10).
    cross_leg_dedup_window_hours: int = 2
    # Module 7 Section 7.1 — AGENT_ASSISTED vs SELF_RECOVERED window (Part E item 11).
    attribution_window_hours: int = 24
    # Module 3 Section 3.3 / Decision E — uncalibrated launch threshold.
    diagnosis_confidence_threshold: float = 0.65
    # Module 8 Section 8.1 — warm-start multiplier bounds (Part E item 12).
    warm_start_cap_low: float = 0.5
    warm_start_cap_high: float = 1.3
    # SystemicEvent resolution sustain window (Decision J).
    systemic_sustain_window_minutes: int = 10
    # NACHRetryPolicy Section 3 — self-imposed representment ceiling. NACH has
    # no NPCI cap; this "recommended default 3 per billing cycle" is what
    # Module 4 copies into Playbook.stopping_rules.max_attempts for NACH
    # playbooks. Consumed by torque.compliance.retry_rails.nach_retry_eligible.
    nach_representment_ceiling_default: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_policy() -> PolicyConfig:
    return PolicyConfig()
