"""Module 4 — Policy & Playbook Engine (Blueprint §4).

Runtime layer on top of the `torque.playbooks` authoring contract: the concrete
demo playbook catalog (§4.1), root-cause → playbook selection, version-pinned
`PlaybookRun` instantiation, the pure "rules for reading" a graph (§4 traversal),
the payday-override policy gate (§4.3), and the `multi_case_template` contract
(§4.4). Execution of the actions — traversal at runtime, timing computation,
guardrail enforcement, Temporal — is Module 5/6.

Public surface:
* `activate_case(session, case_id=...)` / `ActivationOutcome` — run instantiation.
* `resolve_effective_stopping_rules(session, run)` — merchant-effective rules.
* `select_playbook_id(...)` — the §4.1 selection map.
* `seed_catalog(session)` — insert the eleven catalog playbooks (ORM-validated).
"""

from __future__ import annotations

from torque.policy.catalog import CATALOG, CATALOG_BY_ID, seed_catalog
from torque.policy.engine import (
    ActivationOutcome,
    activate_case,
    resolve_effective_stopping_rules,
)
from torque.policy.selection import select_playbook_id

__all__ = [
    "CATALOG",
    "CATALOG_BY_ID",
    "seed_catalog",
    "ActivationOutcome",
    "activate_case",
    "resolve_effective_stopping_rules",
    "select_playbook_id",
]
