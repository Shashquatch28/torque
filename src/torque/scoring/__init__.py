"""Module 8 — Recovery Scoring Model (Blueprint §8).

Computes `(probability × amount_at_risk) ÷ cost` for every open case — the single
economic number that prioritises the Outreach Coordinator, the human queue,
Module 9 reporting, and the future dashboard's top-at-risk view.

The operative model (today): **benchmark probability → warm-start adjustment →
cost-aware recovery score**. Explainable, deterministic, no learned model. The
roadmap upgrade (XGBoost + SHAP + T/X-learner uplift, once 500+ resolved cases
exist — Decision F / §8.4) is deliberately **not** built here.

* `benchmarks` — the Decision F cold-start lookup + §8.2 warm-start multiplier.
* `cost` — the forward intervention cost from `ChannelRateCard` (§8.2).
* `score` — `RecoveryScore` + `compute_recovery_score` (the one authoritative
  formula) + `score_case` / `recompute_open_cases` (the §8.5 persistence).
* `tasks` — the Celery recompute tasks (§8.5).

The `torque.coordination.outreach_coordinator.priority()` seam (D-098) delegates
here — no consumer re-implements the formula.
"""

from __future__ import annotations

from torque.scoring.benchmarks import (
    adjusted_probability,
    cold_start_probability,
    warm_start_multiplier,
)
from torque.scoring.cost import CostBasis, CostBreakdown, NextStepSource, compute_cost
from torque.scoring.score import (
    RecoveryScore,
    compute_recovery_score,
    recompute_open_cases,
    score_case,
)

__all__ = [
    "CostBasis",
    "CostBreakdown",
    "NextStepSource",
    "RecoveryScore",
    "adjusted_probability",
    "cold_start_probability",
    "compute_cost",
    "compute_recovery_score",
    "recompute_open_cases",
    "score_case",
    "warm_start_multiplier",
]
