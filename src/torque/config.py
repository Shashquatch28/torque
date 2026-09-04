"""Runtime configuration and policy values.

Blueprint v7 is explicit (Decision E, Part E items 9-12) that tunable windows
and thresholds are *policy values*, not hardcoded literals. This module is their
single home. Milestone 1 does not consume the policy values below — they are
declared here so that Modules 2, 3, 7, and 8 have a defined place to read them
from instead of scattering magic numbers through the codebase.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
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
    # Which secret the webhook endpoint verifies against. Blueprint 2.2 requires
    # selecting by the mode the request arrived on and never trying both (trying
    # both would silently widen the acceptance criteria). For the single-merchant
    # demo the mode is a per-deployment setting, not a per-request signal.
    razorpay_webhook_mode: Literal["live", "test"] = "test"

    # Blueprint §2.6 / Part D item 1 — checkout abandonment has no Razorpay
    # webhook. The demo-scope default (confirmed) is a signed internal injection
    # endpoint: HMAC-SHA256 over the raw body against this secret, the same
    # pattern as §2.2. Unset → the endpoint fails closed.
    checkout_injection_secret: str | None = None

    # Celery + Redis for the Module 2 inbound self-recovery buffer (Milestone
    # 7b). Broker only — no result backend. Host port 6389 matches the
    # docker-compose redis service. Consumed by `torque.ingestion.celery_app`.
    redis_url: str = "redis://localhost:6389/0"
    # When true the Celery task runs inline (no broker, no worker) — set by the
    # test harness for deterministic tests; never in a real deployment.
    celery_task_always_eager: bool = False

    # API bind address for `python -m torque` (uvicorn). Env TORQUE_API_HOST /
    # TORQUE_API_PORT (Module 11 — one config object instead of __main__ reading
    # os.environ directly). 127.0.0.1 for host dev; the `api` container overrides
    # to 0.0.0.0 so its published port is reachable.
    api_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("api_host", "TORQUE_API_HOST"),
    )
    api_port: int = Field(
        default=8000,
        validation_alias=AliasChoices("api_port", "TORQUE_API_PORT"),
    )

    def active_razorpay_webhook_secret(self) -> str | None:
        """The one webhook secret for this deployment's configured mode.

        Returns ``None`` when that secret is unset — the endpoint then fails
        closed (verification cannot pass, the request is dropped with HTTP 200
        and no ``Event`` row).
        """
        if self.razorpay_webhook_mode == "live":
            return self.razorpay_webhook_secret_live
        return self.razorpay_webhook_secret_test


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
    # Module 6 Part A §5 — Outreach Coordinator minimum quiet period between two
    # outreach events from DIFFERENT legs to the same counterparty at the same
    # merchant. A stated default (4h); consumed by
    # torque.coordination.outreach_coordinator.
    cross_leg_quiet_period_hours: int = 4
    # Module 7 Section 7.1 — AGENT_ASSISTED vs SELF_RECOVERED window (Part E item 11).
    attribution_window_hours: int = 24
    # Module 3 Section 3.3 / Decision E — uncalibrated launch threshold.
    diagnosis_confidence_threshold: float = 0.65
    # Module 8 Section 8.1 — warm-start multiplier bounds (Part E item 12).
    warm_start_cap_low: float = 0.5
    warm_start_cap_high: float = 1.3
    # Module 8 Section 8.2 — the divisor floor for `(probability × amount) ÷ cost`
    # when the forward intervention cost is zero / unpriced / not yet known
    # (D-111). One paisa: keeps the score finite and comparable, and a genuinely
    # free next step still ranks highest — just finitely. Not a blueprint figure
    # (the blueprint is silent on zero cost); the conservative default.
    recovery_score_cost_floor: float = 0.01
    # SystemicEvent threshold + resolution (Blueprint Section 3 / Decision J).
    # `systemic_sustain_window_minutes` gates `resolved_at`; the other three feed
    # `torque.compliance.systemic.systemic_threshold_breached`. N and M are
    # per-scope config values in the blueprint; the numeric defaults below are
    # unverified placeholders (no blueprint figure) to be tuned when Module 2
    # Section 2.5 is built.
    systemic_sustain_window_minutes: int = 10
    # N and M below are U-04 placeholders (no blueprint figure) — configurable,
    # not empirically validated.
    systemic_spike_multiplier: float = 5.0        # Decision J: 5x baseline
    systemic_baseline_floor_per_min: float = 1.0  # N: min baseline failures/min
    systemic_absolute_count_floor: int = 20       # M: min absolute failures in window
    # Module 2 Section 2.5 windows (Milestone 7c). Both are blueprint figures:
    # the detection window is "trailing 10 minutes"; the baseline is a
    # "trailing 7-day" average. Consumed by torque.ingestion.systemic.
    systemic_detection_window_minutes: int = 10
    systemic_baseline_days: int = 7
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
