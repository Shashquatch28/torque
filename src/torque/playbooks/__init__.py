"""Playbook authoring-time contract: the locked `steps_graph` shape, the typed
`stopping_rules` models, merchant-override resolution, and save-time validation
(Blueprint Section 3 / Section 4 / Section 2.4).

Pure — no ORM, no session, no runtime traversal. The `before_flush` guard in
`torque.models.guards` is the single enforcement point.
"""

from torque.playbooks.graph import (
    ActionTemplate,
    EdgeCondition,
    StepEdge,
    StepGraph,
    StepNode,
    parse_step_graph,
    validate_step_graph,
)
from torque.playbooks.resolution import deep_merge, effective_stopping_rules
from torque.playbooks.stopping_rules import (
    AllowedHours,
    PartialAllowedHours,
    PartialStoppingRules,
    StoppingRules,
    parse_partial_stopping_rules,
    parse_stopping_rules,
)
from torque.playbooks.validation import (
    validate_merchant_playbook_config,
    validate_playbook,
)

__all__ = [
    "ActionTemplate",
    "EdgeCondition",
    "StepEdge",
    "StepGraph",
    "StepNode",
    "parse_step_graph",
    "validate_step_graph",
    "deep_merge",
    "effective_stopping_rules",
    "AllowedHours",
    "PartialAllowedHours",
    "PartialStoppingRules",
    "StoppingRules",
    "parse_partial_stopping_rules",
    "parse_stopping_rules",
    "validate_merchant_playbook_config",
    "validate_playbook",
]
