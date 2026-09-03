"""The rules for reading a `steps_graph` — Blueprint §4 ("Module 4's contract
ends at 'here is a valid graph and the rules for reading it'").

Pure functions over a validated `steps_graph` dict. They decide *which node is
next given an outcome*; they do NOT execute actions, mutate `active_step_id`, read
the clock, or touch the DB — all of that is Module 5's runtime traversal
(D-024: `active_step_id` is Module 5's to advance). Module 5 drives these rules
inside its workflow.

Every graph passed here has already cleared `validate_step_graph` at save time
(entry names a node, one `on_success` + ≥1 fallback per non-terminal, no cycles),
so these helpers assume a well-formed graph and raise `PlaybookGraphError` only on
a genuinely absent node/edge (a programming error, never malformed data).
"""

from __future__ import annotations

from typing import Literal

from torque.exceptions import PlaybookGraphError

Outcome = Literal["on_success", "on_no_response", "on_failed", "on_blocked"]


def entry_step_id(graph: dict) -> str:
    """The graph's entry node id — the initial `active_step_id` of a new run."""
    return graph["entry"]


def _nodes(graph: dict) -> dict[str, dict]:
    return {n["id"]: n for n in graph.get("nodes", [])}


def node(graph: dict, step_id: str) -> dict:
    """The node dict for `step_id`. Raises `PlaybookGraphError` if absent."""
    nodes = _nodes(graph)
    if step_id not in nodes:
        raise PlaybookGraphError(f"step {step_id!r} is not a node in this graph")
    return nodes[step_id]


def outgoing_edges(graph: dict, step_id: str) -> list[dict]:
    node(graph, step_id)  # validate the node exists
    return [e for e in graph.get("edges", []) if e["from"] == step_id]


def is_terminal(graph: dict, step_id: str) -> bool:
    """A node with no outgoing edges is terminal — reaching it ends the ladder
    (the run then completes / escalates per Module 5's stopping-rule evaluation)."""
    return not outgoing_edges(graph, step_id)


def next_step_id(graph: dict, step_id: str, outcome: Outcome) -> str | None:
    """The node the run advances to from `step_id` given an action `outcome`, or
    `None` if `step_id` is terminal or has no edge for that outcome.

    Validation guarantees exactly one `on_success` edge and ≥1 fallback on every
    non-terminal node, so a matched outcome resolves to a single target.
    """
    for edge in outgoing_edges(graph, step_id):
        if edge["condition"] == outcome:
            return edge["to"]
    return None


def step_template(node_dict: dict, *, multi_case: bool) -> tuple[str | None, bool]:
    """Resolve the rendering template for a step (Blueprint §4.4).

    Returns `(template, defer_secondary)`:
    * single-case (`multi_case=False`) → the node's `params.template`, no defer;
    * merged outreach (`multi_case=True`) with a `params.multi_case_template` →
      that template, no defer;
    * merged outreach WITHOUT a `multi_case_template` → the single-case
      `params.template` and `defer_secondary=True`, the signal for Module 5 to send
      the higher-priority case's single message and DEFER the other case's outreach
      (`ACTION_BLOCKED` / `OUTREACH_COORDINATOR_DEFERRED`), never silently drop it.
    """
    params = node_dict.get("params") or {}
    single = params.get("template")
    if not multi_case:
        return single, False
    multi = params.get("multi_case_template")
    if multi is not None:
        return multi, False
    return single, True
