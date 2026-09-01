"""Merchant stopping-rules override resolution (Blueprint Section 4.2 / decision A).

    effective_stopping_rules = deep_merge(playbook.stopping_rules, override)
                               followed by full validation

Resolution semantics (decision 6):
* `stopping_rules_override IS NULL` (or `{}`)  -> effective = base playbook rules
* a non-null override                          -> deep_merge(base, override), then validate

`MerchantPlaybookConfig.enabled` does NOT participate in rule resolution. It
governs whether the playbook is available for merchant selection / execution —
that behaviour is deferred to Module 4 / runtime.

`deep_merge` semantics (decision 6), applied recursively:
* dict + dict   -> recurse
* scalar        -> override value replaces base value
* list          -> override list replaces the base list wholesale (NO element-level merge)
"""

from __future__ import annotations

import copy

from torque.playbooks.stopping_rules import StoppingRules


def deep_merge(base: dict, override: dict | None) -> dict:
    """Recursively merge `override` onto `base` (see module docstring for the
    exact semantics). Neither argument is mutated; a new dict is returned."""
    result = copy.deepcopy(base)
    if not override:
        return result
    for key, ov in override.items():
        bv = result.get(key)
        if isinstance(bv, dict) and isinstance(ov, dict):
            result[key] = deep_merge(bv, ov)
        else:
            result[key] = copy.deepcopy(ov)
    return result


def effective_stopping_rules(base: dict, override: dict | None) -> StoppingRules:
    """The validated stopping rules a run would actually use. Raises
    `PlaybookValidationError` if the merged result violates `StoppingRules`."""
    from torque.playbooks.stopping_rules import parse_stopping_rules

    return parse_stopping_rules(deep_merge(base, override))
