"""Save-time playbook validation (Blueprint Section 4.2).

"Catching a bad playbook before it can ever run is cheaper than catching it
mid-execution." These functions are invoked by the `before_flush` guard
(`torque.models.guards`) — never a caller-remembered helper.

The UPI AutoPay `max_attempts <= 3` rule is enforced here as **defense-in-depth**
against `UPIRetryBudget.hard_cap` (which stays independently enforced at runtime,
Module 5). The shared constant is imported from the compliance layer so both
paths reject the same value.
"""

from __future__ import annotations

from torque.compliance.retry_rails import UPI_AUTOPAY_HARD_CAP
from torque.enums import LegType, MandateType
from torque.exceptions import PlaybookValidationError
from torque.playbooks.graph import parse_step_graph
from torque.playbooks.resolution import effective_stopping_rules
from torque.playbooks.stopping_rules import (
    StoppingRules,
    parse_partial_stopping_rules,
    parse_stopping_rules,
)


def _check_upi_ceiling(mandate_type: MandateType | None, rules: StoppingRules) -> None:
    if (
        mandate_type is not None
        and MandateType(mandate_type) is MandateType.UPI_AUTOPAY
        and rules.max_attempts > UPI_AUTOPAY_HARD_CAP
    ):
        raise PlaybookValidationError(
            f"UPI AutoPay playbook max_attempts={rules.max_attempts} exceeds the "
            f"NPCI-enforced ceiling of {UPI_AUTOPAY_HARD_CAP} (Section 4.2)"
        )


def _check_escalation_ceiling(rules: StoppingRules) -> None:
    """Module 6 §6.3 (Q-D): `escalation_ceiling` is a sub-bound on the run's
    unsuccessful attempts and must not exceed `max_attempts` — otherwise a run
    could exhaust its attempt cap before the ceiling could ever route it to a
    human. Enforced at playbook-save time, on the base rules and on any merchant
    override merged onto them (the same defense-in-depth path as the UPI cap)."""
    if rules.escalation_ceiling > rules.max_attempts:
        raise PlaybookValidationError(
            f"escalation_ceiling={rules.escalation_ceiling} exceeds "
            f"max_attempts={rules.max_attempts} (Module 6 §6.3 — the ceiling is a "
            f"sub-bound on unsuccessful attempts, it cannot exceed the attempt cap)"
        )


def validate_playbook(
    *,
    leg_type: LegType,
    mandate_type: MandateType | None,
    steps_graph: dict,
    stopping_rules: dict,
) -> tuple[dict, dict]:
    """Validate a `playbook` version at save time. Returns the normalised
    `(steps_graph, stopping_rules)` JSON dicts to persist. Raises
    `PlaybookValidationError` on any violation.

    `leg_type` is accepted for symmetry / future leg-specific rules; it is not
    currently constrained here.
    """
    LegType(leg_type)  # validate enum membership
    graph = parse_step_graph(steps_graph)
    rules = parse_stopping_rules(stopping_rules)
    _check_upi_ceiling(mandate_type, rules)
    _check_escalation_ceiling(rules)
    return graph.to_json_dict(), rules.model_dump(mode="json")


def validate_merchant_playbook_config(
    *,
    latest_leg_type: LegType,
    latest_mandate_type: MandateType | None,
    latest_stopping_rules: dict,
    override: dict | None,
) -> dict | None:
    """Validate a `MerchantPlaybookConfig` against the **latest** published
    version of its playbook (decision 2):

    * the override, if present, must be a well-formed `PartialStoppingRules`;
    * `deep_merge(latest_stopping_rules, override)` must be a valid
      `StoppingRules`;
    * that merged result is subject to the same UPI AutoPay ceiling, keyed off
      the latest version's `mandate_type`.

    Returns the normalised override JSON (or ``None``). Raises
    `PlaybookValidationError` on any violation.
    """
    LegType(latest_leg_type)
    normalised: dict | None = None
    if override:
        normalised = parse_partial_stopping_rules(override).model_dump(
            mode="json", exclude_none=True
        )
    effective = effective_stopping_rules(latest_stopping_rules, override)
    _check_upi_ceiling(latest_mandate_type, effective)
    _check_escalation_ceiling(effective)
    return normalised
