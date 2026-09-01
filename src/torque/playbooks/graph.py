"""`steps_graph` — the locked format contract (Blueprint Section 3).

    { "entry": "s1",
      "nodes": [ { "id": "s1", "action_template": { "type": "SEND_WHATSAPP", ... },
                   "timing_offset_hours": 0, "params": {...} } ],
      "edges": [ { "from": "s1", "condition": "on_success", "to": "s3" } ] }

Module 4 writes it, Module 5 traverses it. This module owns the authoring-time
*shape* + structural rules; runtime traversal is Module 5.

Structural rules (Section 3 / Section 4.2), enforced by `validate_step_graph`:
* `entry` names an existing node
* every edge endpoint names an existing node; node ids are unique
* every NON-terminal node has exactly one `on_success` edge and >= 1 fallback
  (`on_no_response` / `on_blocked` / `on_failed`)
* no cycles — a step may never loop back to an earlier step
* a terminal node = a node with no outgoing edges

`action_template.type` is validated against the `ActionType` enum here (decision
E); action-specific `params` schemas are deferred to Module 5.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from torque.enums import ActionType
from torque.exceptions import PlaybookValidationError

EdgeCondition = Literal["on_success", "on_no_response", "on_blocked", "on_failed"]
_FALLBACK_CONDITIONS = frozenset({"on_no_response", "on_blocked", "on_failed"})


class ActionTemplate(BaseModel):
    """`{ "type": <ActionType>, ...arbitrary action params... }`.

    `type` is required and validated now; extra keys are permitted and pass
    through unvalidated (decision E) so future action metadata needs no schema
    migration.
    """

    model_config = ConfigDict(extra="allow")

    type: ActionType


class StepEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    condition: EdgeCondition
    to: str


class StepNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action_template: ActionTemplate
    timing_offset_hours: float = Field(ge=0)
    params: dict = Field(default_factory=dict)


class StepGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry: str
    nodes: list[StepNode]
    edges: list[StepEdge]

    def to_json_dict(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)


def _has_cycle(node_ids: list[str], edges: list[StepEdge]) -> bool:
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for e in edges:
        adj[e.from_].append(e.to)

    white, gray, black = 0, 1, 2
    color = dict.fromkeys(node_ids, white)

    def visit(u: str) -> bool:
        color[u] = gray
        for v in adj[u]:
            if color[v] == gray:
                return True
            if color[v] == white and visit(v):
                return True
        color[u] = black
        return False

    return any(color[nid] == white and visit(nid) for nid in node_ids)


def validate_step_graph(graph: StepGraph) -> None:
    """Structural validation of an already-parsed `StepGraph`. Raises
    `PlaybookValidationError` on the first violation."""
    node_ids = [n.id for n in graph.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise PlaybookValidationError("steps_graph has duplicate node ids")
    ids = set(node_ids)

    if not node_ids:
        raise PlaybookValidationError("steps_graph has no nodes")
    if graph.entry not in ids:
        raise PlaybookValidationError(
            f"steps_graph entry {graph.entry!r} is not a node id"
        )

    out_edges: dict[str, list[StepEdge]] = {nid: [] for nid in node_ids}
    for e in graph.edges:
        if e.from_ not in ids:
            raise PlaybookValidationError(f"edge from unknown node {e.from_!r}")
        if e.to not in ids:
            raise PlaybookValidationError(f"edge to unknown node {e.to!r}")
        out_edges[e.from_].append(e)

    for nid in node_ids:
        edges = out_edges[nid]
        if not edges:
            continue  # terminal node — triggers stopping-rule evaluation at runtime
        on_success = [e for e in edges if e.condition == "on_success"]
        if len(on_success) != 1:
            raise PlaybookValidationError(
                f"non-terminal node {nid!r} must have exactly one on_success edge "
                f"(has {len(on_success)})"
            )
        if not any(e.condition in _FALLBACK_CONDITIONS for e in edges):
            raise PlaybookValidationError(
                f"non-terminal node {nid!r} must have at least one fallback edge "
                f"(on_no_response / on_blocked / on_failed)"
            )

    if _has_cycle(node_ids, graph.edges):
        raise PlaybookValidationError(
            "steps_graph contains a cycle — a step may never loop back "
            "(bound repetition via stopping_rules instead)"
        )


def parse_step_graph(raw: dict) -> StepGraph:
    """Parse `raw` into a `StepGraph` and run structural validation. Every
    failure — shape, `action_template.type`, or structure — surfaces as
    `PlaybookValidationError`."""
    from pydantic import ValidationError

    try:
        graph = StepGraph.model_validate(raw)
    except ValidationError as exc:
        raise PlaybookValidationError(
            f"malformed steps_graph: {exc.errors(include_url=False)}"
        ) from exc
    validate_step_graph(graph)
    return graph
