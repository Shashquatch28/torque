"""Payday-cycle override — the policy half of Blueprint §4.3.

Module 3 *emits* `suggested_timing_adjustment` on the case (a signal). Module 4
*owns the policy decision* of whether that signal is actually applied to timing;
Module 5 performs the runtime substitution when it computes "when does this node
fire" (D-025 — the timing computation itself is Module 5's).

`payday_cycle_override_enabled` is a merchant config value (default **true**,
§4.3). It lives in the existing `Merchant.risk_appetite_config` JSONB bag rather
than a dedicated column — no schema change, and `risk_appetite_config` is exactly
the "default max attempts / escalation ceiling, etc." home the model documents
(D-087).
"""

from __future__ import annotations

from torque.models import Merchant
from torque.models.revenue_leak_case import RevenueLeakCase

PAYDAY_OVERRIDE_KEY = "payday_cycle_override_enabled"


def payday_override_enabled(merchant: Merchant) -> bool:
    """Whether this merchant applies the §4.3 payday-cycle timing override.
    Default `True` when unset (§4.3)."""
    config = merchant.risk_appetite_config or {}
    value = config.get(PAYDAY_OVERRIDE_KEY, True)
    return bool(value)


def effective_timing_adjustment(case: RevenueLeakCase, merchant: Merchant) -> str | None:
    """The timing adjustment Module 5 should actually apply for this case: the
    diagnosis's `suggested_timing_adjustment` **iff** the merchant has the override
    enabled, else `None` (the graph's static `timing_offset_hours` stands). This is
    the policy gate — it never computes a fire time (that is Module 5)."""
    if not payday_override_enabled(merchant):
        return None
    return case.suggested_timing_adjustment
