"""Blueprint Section 3 / Section 4.2 - `steps_graph` locked format + structural
rules. Pure, no DB."""

from __future__ import annotations

from copy import deepcopy

import pytest

from torque.exceptions import PlaybookValidationError
from torque.playbooks import StepGraph, parse_step_graph, validate_step_graph

LINEAR = {
    "entry": "a",
    "nodes": [
        {"id": "a", "action_template": {"type": "SEND_WHATSAPP"}, "timing_offset_hours": 0},
        {"id": "b", "action_template": {"type": "ESCALATE_HUMAN"}, "timing_offset_hours": 12},
    ],
    "edges": [
        {"from": "a", "condition": "on_success", "to": "b"},
        {"from": "a", "condition": "on_no_response", "to": "b"},
    ],
}


def _g(mut=None) -> dict:
    g = deepcopy(LINEAR)
    if mut:
        mut(g)
    return g


# --- accept ------------------------------------------------------------


def test_valid_linear_graph_accepted():
    parse_step_graph(_g())


def test_single_node_terminal_graph_accepted():
    parse_step_graph(
        {
            "entry": "only",
            "nodes": [
                {
                    "id": "only",
                    "action_template": {"type": "RETRY_PAYMENT"},
                    "timing_offset_hours": 0,
                }
            ],
            "edges": [],
        }
    )


def test_branching_graph_accepted():
    parse_step_graph(
        {
            "entry": "a",
            "nodes": [
                {"id": "a", "action_template": {"type": "SEND_WHATSAPP"}, "timing_offset_hours": 0},
                {"id": "b", "action_template": {"type": "SEND_EMAIL"}, "timing_offset_hours": 1},
                {
                    "id": "c",
                    "action_template": {"type": "ESCALATE_HUMAN"},
                    "timing_offset_hours": 2,
                },
            ],
            "edges": [
                {"from": "a", "condition": "on_success", "to": "b"},
                {"from": "a", "condition": "on_failed", "to": "c"},
                {"from": "b", "condition": "on_success", "to": "c"},
                {"from": "b", "condition": "on_blocked", "to": "c"},
            ],
        }
    )


def test_action_template_extra_params_allowed():
    g = _g()
    g["nodes"][0]["action_template"] = {"type": "SEND_WHATSAPP", "template_name": "nudge_v1"}
    parsed = parse_step_graph(g)
    assert parsed.nodes[0].action_template.type == "SEND_WHATSAPP"


# --- reject: Pydantic shape -----------------------------------------


def test_bad_action_type_rejected():
    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(lambda g: g["nodes"][0]["action_template"].__setitem__("type", "NOPE")))


def test_missing_action_type_rejected():
    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(lambda g: g["nodes"][0].__setitem__("action_template", {})))


def test_negative_timing_offset_rejected():
    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(lambda g: g["nodes"][0].__setitem__("timing_offset_hours", -1)))


def test_unknown_key_on_node_rejected():
    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(lambda g: g["nodes"][0].__setitem__("weight", 5)))


def test_bad_condition_literal_rejected():
    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(lambda g: g["edges"][0].__setitem__("condition", "on_maybe")))


# --- reject: structural -------------------------------------------


def test_unknown_entry_rejected():
    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(lambda g: g.__setitem__("entry", "ghost")))


def test_dangling_edge_from_rejected():
    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(lambda g: g["edges"][0].__setitem__("from", "ghost")))


def test_dangling_edge_to_rejected():
    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(lambda g: g["edges"][0].__setitem__("to", "ghost")))


def test_duplicate_node_id_rejected():
    def mut(g):
        g["nodes"].append(
            {"id": "a", "action_template": {"type": "SEND_SMS"}, "timing_offset_hours": 0}
        )

    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(mut))


def test_non_terminal_without_on_success_rejected():
    def mut(g):
        g["edges"][0] = {"from": "a", "condition": "on_failed", "to": "b"}

    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(mut))


def test_non_terminal_with_two_on_success_rejected():
    def mut(g):
        g["edges"][1] = {"from": "a", "condition": "on_success", "to": "b"}

    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(mut))


def test_non_terminal_without_fallback_rejected():
    def mut(g):
        g["edges"] = [{"from": "a", "condition": "on_success", "to": "b"}]

    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(mut))


def test_self_loop_cycle_rejected():
    def mut(g):
        g["edges"].append({"from": "b", "condition": "on_success", "to": "b"})
        g["edges"].append({"from": "b", "condition": "on_failed", "to": "b"})

    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(mut))


def test_back_edge_cycle_rejected():
    def mut(g):
        # a -> b already; add b -> a (with its required edges) to close a loop
        g["edges"].append({"from": "b", "condition": "on_success", "to": "a"})
        g["edges"].append({"from": "b", "condition": "on_blocked", "to": "a"})

    with pytest.raises(PlaybookValidationError):
        parse_step_graph(_g(mut))


def test_validate_step_graph_accepts_parsed_model():
    validate_step_graph(StepGraph.model_validate(LINEAR))
