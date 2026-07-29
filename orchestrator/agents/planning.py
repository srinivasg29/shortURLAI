from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from orchestrator.llm import call_llm, is_live
from orchestrator.state import GateLogEntry, OrchestratorState

SYSTEM_PROMPT = """You are the Planning Agent in an agentic SDLC orchestrator for a URL \
shortener service. Given a normalized engineering spec, decompose it into actionable tasks \
with explicit dependencies, matching this orchestrator's own downstream phases (design, \
implementation, testing, documentation, review).

Respond with ONLY a JSON object (no prose, no markdown fences):
{
  "tasks": [
    {"id": "<short-id>", "description": "<what this task does>", "depends_on": ["<id>", ...]}
  ]
}
Use 4-6 tasks. IDs must be unique. depends_on must reference only ids defined in this list.
The graph must be acyclic and every task must be reachable from at least one task with no
dependencies."""


def _extract_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(match.group(0) if match else raw)


def default_task_graph(normalized_spec: str, replan_reason: str | None = None) -> dict[str, Any]:
    """Deterministic fallback: a standard design -> implement -> (test + document) -> review
    decomposition, mirroring the orchestrator's own downstream phases.

    When re-entered after a re-plan (replan_reason set), inserts a
    "remediate" task ahead of "design" that names the specific failure that
    triggered the re-plan - this is what makes a re-plan a genuine
    plan-graph change rather than a no-op retry that just re-derives the
    same task_graph from the same normalized_spec."""
    design_depends_on: list[str] = []
    tasks: list[dict[str, Any]] = []

    if replan_reason:
        tasks.append(
            {
                "id": "remediate",
                "description": f"Address prior failure before re-attempting: {replan_reason}",
                "depends_on": [],
            }
        )
        design_depends_on = ["remediate"]

    tasks.extend(
        [
            {
                "id": "design",
                "description": f"Design the change: {normalized_spec}",
                "depends_on": design_depends_on,
            },
            {
                "id": "implement",
                "description": "Implement the change in the URL shortener service",
                "depends_on": ["design"],
            },
            {
                "id": "test",
                "description": "Add/update unit and integration tests for the change",
                "depends_on": ["implement"],
            },
            {
                "id": "document",
                "description": "Update README/API docs for the change",
                "depends_on": ["implement"],
            },
            {
                "id": "review",
                "description": "Prepare the change for quality review and release readiness",
                "depends_on": ["test", "document"],
            },
        ]
    )
    return {"tasks": tasks}


def validate_task_graph(task_graph: dict[str, Any]) -> tuple[bool, str]:
    tasks = task_graph.get("tasks")
    if not tasks:
        return False, "task_graph has no tasks"

    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        return False, "duplicate task ids"

    id_set = set(ids)
    for task in tasks:
        for dep in task.get("depends_on", []):
            if dep not in id_set:
                return False, f"task {task['id']!r} depends on unknown task {dep!r}"

    # Cycle check via Kahn's algorithm: if topological sort can't visit every
    # task, some subset only reaches itself through a cycle.
    in_degree = {t["id"]: 0 for t in tasks}
    adjacency: dict[str, list[str]] = {t["id"]: [] for t in tasks}
    for task in tasks:
        for dep in task.get("depends_on", []):
            adjacency[dep].append(task["id"])
            in_degree[task["id"]] += 1

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    if not queue:
        return False, "task_graph has no root task (every task has a dependency)"

    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for neighbor in adjacency[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(tasks):
        return False, "task_graph contains a cycle"

    return True, "task_graph is acyclic with all dependencies resolvable"


def _last_replan_reason(state: OrchestratorState) -> str | None:
    replan_log = state.get("replan_log", [])
    return replan_log[-1]["trigger_reason"] if replan_log else None


def _plan(normalized_spec: str, replan_reason: str | None) -> tuple[dict[str, Any], str]:
    if is_live():
        try:
            prompt = normalized_spec
            if replan_reason:
                prompt = (
                    f"{normalized_spec}\n\nNote: a prior attempt at this failed and the graph "
                    f"routed back here to re-plan. Reason: {replan_reason}\nAdjust the task "
                    f"breakdown to address it (e.g. add a remediation task) rather than "
                    f"repeating the same plan verbatim."
                )
            raw = call_llm(SYSTEM_PROMPT, prompt)
            parsed = _extract_json(raw)
            valid, _ = validate_task_graph(parsed)
            if valid:
                return parsed, "live"
        except Exception:
            pass
    return default_task_graph(normalized_spec, replan_reason), "mock"


def run(state: OrchestratorState) -> OrchestratorState:
    normalized_spec = state["normalized_spec"]
    replan_reason = _last_replan_reason(state)
    task_graph, llm_mode = _plan(normalized_spec, replan_reason)

    valid, detail = validate_task_graph(task_graph)
    if not valid:
        # Even the deterministic fallback must satisfy this; if it somehow
        # doesn't, fail closed rather than hand a broken graph downstream.
        task_graph = default_task_graph(normalized_spec, replan_reason)
        valid, detail = validate_task_graph(task_graph)
        llm_mode = "mock"

    gate_entry: GateLogEntry = {
        "gate_id": "gate_1",
        "node": "planning_agent",
        "passed": valid,
        "approver": "system",
        "entry_criteria": "normalized_spec available",
        "exit_criteria": "task graph + dependencies set",
        "timestamp": datetime.now(UTC).isoformat(),
        "detail": detail,
    }

    result: OrchestratorState = {
        "task_graph": task_graph,
        "gate_log": [gate_entry],
    }
    # llm_mode is a whole-run flag set by the first node; only downgrade it
    # here, never upgrade, so the audit trail reflects the worst case across
    # all nodes rather than just the last one to run.
    if llm_mode == "mock":
        result["llm_mode"] = "mock"
    return result
