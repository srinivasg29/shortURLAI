from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from orchestrator import audit
from orchestrator.agents import (
    architecture,
    coding,
    documentation,
    planning,
    requirement,
    sync,
    testing,
)
from orchestrator.state import OrchestratorState


def _requirement_node(state: OrchestratorState) -> OrchestratorState:
    result = requirement.run(state)
    for entry in result.get("gate_log", []):
        audit.append_event({"type": "gate", **entry})
    return result


def _planning_node(state: OrchestratorState) -> OrchestratorState:
    result = planning.run(state)
    for entry in result.get("gate_log", []):
        audit.append_event({"type": "gate", **entry})
    return result


def _architecture_node(state: OrchestratorState) -> OrchestratorState:
    result = architecture.run(state)
    for entry in result.get("gate_log", []):
        audit.append_event({"type": "gate", **entry})
    return result


def _coding_node(state: OrchestratorState) -> OrchestratorState:
    result = coding.run(state)
    for entry in result.get("gate_log", []):
        audit.append_event({"type": "gate", **entry})
    for diff in result.get("code_diffs", []):
        audit.append_event({"type": "code_diff", **diff})
    return result


def _testing_node(state: OrchestratorState) -> OrchestratorState:
    result = testing.run(state)
    for tr in result.get("test_results", []):
        audit.append_event({"type": "test_result", **tr})
    return result


def _documentation_node(state: OrchestratorState) -> OrchestratorState:
    result = documentation.run(state)
    for diff in result.get("doc_diffs", []):
        audit.append_event({"type": "doc_diff", **diff})
    return result


def _gate4_sync_node(state: OrchestratorState) -> OrchestratorState:
    result = sync.run_gate4(state)
    for entry in result.get("gate_log", []):
        audit.append_event({"type": "gate", **entry})
    return result


@lru_cache
def build_graph():
    """Compiled once and cached: the checkpointer backing Gate 2's
    interrupt/resume must be the same instance across a run's start and
    resume calls, since it's what holds the paused state in memory."""
    graph = StateGraph(OrchestratorState)
    graph.add_node("requirement", _requirement_node)
    graph.add_node("planning", _planning_node)
    graph.add_node("architecture", _architecture_node)
    graph.add_node("coding", _coding_node)
    graph.add_node("testing", _testing_node)
    graph.add_node("documentation", _documentation_node)
    graph.add_node("gate4_sync", _gate4_sync_node)

    graph.set_entry_point("requirement")
    graph.add_edge("requirement", "planning")
    graph.add_edge("planning", "architecture")
    graph.add_edge("architecture", "coding")

    # Fan-out: Testing and Documentation both run off Coding's output.
    graph.add_edge("coding", "testing")
    graph.add_edge("coding", "documentation")
    # Fan-in: gate4_sync only runs once both branches have completed: this
    # is what makes Gate 4 a real synchronization point, not two independent
    # checks that happen to share a name.
    graph.add_edge("testing", "gate4_sync")
    graph.add_edge("documentation", "gate4_sync")
    graph.add_edge("gate4_sync", END)

    return graph.compile(checkpointer=InMemorySaver())


def start_run(raw_requirement: str, scenario: str = "adhoc") -> OrchestratorState:
    """Starts a new run. If AUTO_APPROVE is unset, this returns as soon as the
    graph hits Gate 2 — the returned state carries an "__interrupt__" key;
    call resume_run(state["run_id"], decision) to continue."""
    app = build_graph()
    run_id = str(uuid.uuid4())
    audit.append_event(
        {
            "type": "run_start",
            "run_id": run_id,
            "scenario": scenario,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    initial_state: OrchestratorState = {
        "run_id": run_id,
        "scenario": scenario,
        "raw_requirement": raw_requirement,
    }
    config = {"configurable": {"thread_id": run_id}}
    result = app.invoke(initial_state, config)
    result.setdefault("run_id", run_id)
    return result


def resume_run(run_id: str, decision: dict[str, Any] | bool) -> OrchestratorState:
    """Resumes a run paused at a human-approval gate with the human's decision,
    e.g. {"approved": True, "approver": "human:sri", "comment": "looks good"}."""
    app = build_graph()
    config = {"configurable": {"thread_id": run_id}}
    audit.append_event(
        {
            "type": "gate_resume",
            "run_id": run_id,
            "decision": decision,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    return app.invoke(Command(resume=decision), config)
