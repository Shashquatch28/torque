"""Module 10 — deterministic demo data + one-click synthetic scenarios
(Blueprint §10.9 / §10.10 / §10.16).

* `seed` — `seed_demo(session)` builds a fixed, realistic `acc_demo` dataset
  (recovered / blocked / deferred / escalated / unresolved cases across all four
  legs, each with a `CaseEvent` trail, all scored by Module 8). The dashboard
  numbers come from these rows — nothing is hard-coded in the UI.
* `scenarios` — `inject(...)` composes the *existing* ingestion / compliance
  code into visible one-click demo events (checkout abandonment, a payment
  failure, and the Decision-K hard-stop-MAC / UPI-cap / NACH-ceiling
  block scenarios). It invents no parallel event mechanism.

Demo-only. Guarded writes (`recovery_type` / `recovered_amount`) go through the
real `module7_writer`, simulating what reconciliation would have recorded.
"""

from __future__ import annotations

from torque.demo.scenarios import DEMO_SCENARIOS, inject_scenario
from torque.demo.seed import DEMO_MERCHANT_ID, seed_demo

__all__ = [
    "DEMO_MERCHANT_ID",
    "DEMO_SCENARIOS",
    "inject_scenario",
    "seed_demo",
]
