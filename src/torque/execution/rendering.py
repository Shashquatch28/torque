"""Action-context rendering — Blueprint §4.4 / §5 (Module 5 owns rendering).

Module 4 chose *which* template applies (`torque.policy.traversal.step_template`);
Module 5 builds the context the template renders against. For a merged outreach
(the Outreach Coordinator, Module 6, folds two cases for one counterparty into a
single `Action` — Part A §5 / §4.4) the context interpolates **both** cases'
outstanding amounts, and attribution is the existing `ActionCase` split (D-016) —
never a second attribution model.

The live execution loop currently renders single-case (the Outreach Coordinator
merge trigger is Module 6, deferred); this module provides the merged-render
contract and is exercised directly so the one-ledger attribution is proven now.
Superseded cases are never treated as canonical — the caller filters
`superseded_by_case_id IS NULL` before assembling the context.
"""

from __future__ import annotations

from decimal import Decimal

from torque.models import RevenueLeakCase
from torque.policy.traversal import step_template


def resolve_template(node: dict, *, case_count: int) -> tuple[str | None, bool]:
    """The template + defer signal for a step given how many cases it renders for.
    `case_count > 1` is the merged-outreach path (§4.4)."""
    return step_template(node, multi_case=case_count > 1)


def multi_case_context(cases: list[RevenueLeakCase]) -> dict:
    """The interpolation context for a (possibly merged) outreach action: each
    case's outstanding amount plus the combined total. Single-case is the len==1
    case. Callers must pass only canonical (non-superseded) cases."""
    for case in cases:
        if case.superseded_by_case_id is not None:
            raise ValueError(
                f"case {case.case_id} is superseded — a merged render must use "
                f"canonical cases only (§2.4)"
            )
    entries = [
        {"case_id": str(c.case_id), "amount_at_risk": str(c.amount_at_risk)} for c in cases
    ]
    total = sum((Decimal(str(c.amount_at_risk)) for c in cases), Decimal("0"))
    return {"cases": entries, "combined_amount": str(total), "is_merged": len(cases) > 1}
