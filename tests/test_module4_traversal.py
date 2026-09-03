"""Module 4 — the pure "rules for reading" a graph (Blueprint §4 / §4.4). No DB."""

from __future__ import annotations

import pytest

from torque.exceptions import PlaybookGraphError
from torque.policy import catalog as C
from torque.policy.traversal import (
    entry_step_id,
    is_terminal,
    next_step_id,
    node,
    step_template,
)

_GRAPH = C.CATALOG_BY_ID[C.PLAYBOOK_NSF_RETRY].steps_graph  # retry → nudge → escalate


def test_entry_step():
    assert entry_step_id(_GRAPH) == "retry"


def test_next_step_on_success_and_fallbacks():
    assert next_step_id(_GRAPH, "retry", "on_success") == "nudge"
    assert next_step_id(_GRAPH, "retry", "on_failed") == "nudge"
    assert next_step_id(_GRAPH, "nudge", "on_no_response") == "escalate"


def test_terminal_node_has_no_next():
    assert is_terminal(_GRAPH, "escalate") is True
    assert is_terminal(_GRAPH, "retry") is False
    assert next_step_id(_GRAPH, "escalate", "on_success") is None


def test_unknown_node_raises():
    with pytest.raises(PlaybookGraphError):
        node(_GRAPH, "ghost")
    with pytest.raises(PlaybookGraphError):
        next_step_id(_GRAPH, "ghost", "on_success")


def test_single_case_template():
    n = node(_GRAPH, "nudge")
    template, defer = step_template(n, multi_case=False)
    assert template == "nsf_nudge"
    assert defer is False


def test_multi_case_template_used_when_present():
    graph = C.CATALOG_BY_ID[C.PLAYBOOK_B2B_LOW_RISK_DUNNING].steps_graph
    n = node(graph, "email_1")
    template, defer = step_template(n, multi_case=True)
    assert template == "b2b_gentle_multi"
    assert defer is False


def test_multi_case_without_template_signals_defer():
    # PLAYBOOK_NSF_RETRY's nudge has only a single-case template.
    n = node(_GRAPH, "nudge")
    template, defer = step_template(n, multi_case=True)
    assert template == "nsf_nudge"  # falls back to the single-case message
    assert defer is True  # → Module 5 defers the secondary case's outreach
