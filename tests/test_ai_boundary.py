"""The AI subsystem's structurally-enforced read-only boundary.

This test does not run or exercise `torque.ai` code — it statically parses
every `.py` file under `src/torque/ai/` (via `ast`, no execution) and asserts
none of them import anything from a module that can transition a case,
execute an action, write a `CaseEvent`/`Action`, or otherwise mutate Torque's
business state. A future contributor who adds such an import breaks this
test, in CI, before merge — the boundary is a repository fact enforced by
tooling, not a code-review courtesy or a comment someone has to remember to
check.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AI_PACKAGE = REPO_ROOT / "src" / "torque" / "ai"

#: Module-path prefixes `torque.ai.*` must never import — anything at or
#: below one of these can transition a case, execute an action, write a
#: CaseEvent/Action, or otherwise mutate Torque's authoritative state.
#: See documentation/ai-memory/AI_BLUEPRINT.md "Security model" for the
#: reasoning behind each entry.
FORBIDDEN_PREFIXES = (
    "torque.state_machine",  # transition_case, apply_network_directive, sync_control_group
    "torque.coordination",  # GuardrailEngine, merge, human_queue.enqueue, outreach_coordinator
    "torque.events",  # append_case_event, write_action_and_event
    "torque.agent_console",  # resolve_escalation, pause_case, unpause_case
    "torque.execution",  # action execution / the runner / the scheduler
    "torque.ingestion",  # case creation, dispatch_diagnosis
    "torque.policy",  # activate_case, playbook selection writes
    "torque.diagnosis",  # diagnose_case_task, classifier + engine writes
    "torque.scoring",  # score_case / recompute_open_cases (writes)
    "torque.reconciliation",  # reconcile_event (writes recovery_type/recovered_amount)
    "torque.promises",  # transition_promise (writes PromiseToPay.status)
    "torque.api",  # every existing router; torque.ai's own router is a future phase
)


def _imported_module_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import within torque.ai itself — always safe
            if node.module:
                names.add(node.module)
    return names


def _is_forbidden(module_name: str) -> str | None:
    for prefix in FORBIDDEN_PREFIXES:
        if module_name == prefix or module_name.startswith(prefix + "."):
            return prefix
    return None


def _ai_source_files() -> list[Path]:
    assert AI_PACKAGE.is_dir(), f"expected an AI package at {AI_PACKAGE}"
    return sorted(AI_PACKAGE.rglob("*.py"))


def test_ai_package_exists_and_has_source_files():
    files = _ai_source_files()
    assert files, "torque.ai has no source files to check"


def test_ai_package_imports_no_forbidden_module():
    violations: list[str] = []
    for path in _ai_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module_name in _imported_module_names(tree):
            forbidden = _is_forbidden(module_name)
            if forbidden is not None:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}: imports {module_name!r} "
                    f"(forbidden prefix {forbidden!r})"
                )
    assert not violations, (
        "torque.ai must never import a mutation-capable domain module:\n"
        + "\n".join(violations)
    )


def test_forbidden_prefix_detection_itself_works():
    """The detector must actually be able to fail — proves the assertion
    above isn't vacuously passing because the matcher is broken."""
    assert _is_forbidden("torque.state_machine") == "torque.state_machine"
    assert _is_forbidden("torque.events.case_event_writer") == "torque.events"
    assert _is_forbidden("torque.coordination.guardrail_engine") == "torque.coordination"
    assert _is_forbidden("torque.ingestion.tasks") == "torque.ingestion"
    # a module that merely starts with the same letters is NOT a false positive
    assert _is_forbidden("torque.eventsomethingelse") is None
    # allowed reads used by torque.ai itself
    assert _is_forbidden("torque.db.scoped") is None
    assert _is_forbidden("torque.models") is None
    assert _is_forbidden("torque.enums") is None
    assert _is_forbidden("torque.exceptions") is None
    assert _is_forbidden("torque.ai.evidence") is None


def test_ai_package_writes_nothing_at_the_source_level():
    """Defense-in-depth beyond the import check: no file under `torque.ai`
    calls `session.add(`, `.flush(` on anything but a read, `.commit(`, or
    `.delete(` as a raw substring — even a hypothetical future contributor
    who avoided the forbidden imports entirely by hand-rolling SQL should
    still trip something. This is deliberately crude (substring, not AST) —
    a second, independent signal alongside the precise import-graph check
    above, not a replacement for it.
    """
    forbidden_substrings = (
        ".add(",
        ".delete(",
        ".commit(",
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
    )
    violations: list[str] = []
    for path in _ai_source_files():
        text = path.read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            if needle in text:
                violations.append(f"{path.relative_to(REPO_ROOT)}: contains {needle!r}")
    assert not violations, (
        "torque.ai source must contain no write-shaped call or raw SQL "
        "mutation:\n" + "\n".join(violations)
    )
