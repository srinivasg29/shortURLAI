from __future__ import annotations

import uuid
from datetime import UTC, datetime

from langgraph.graph import END, StateGraph

from orchestrator import audit
from orchestrator.agents import planning, requirement
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


def build_graph():
    graph = StateGraph(OrchestratorState)
    graph.add_node("requirement", _requirement_node)
    graph.add_node("planning", _planning_node)
    graph.set_entry_point("requirement")
    graph.add_edge("requirement", "planning")
    graph.add_edge("planning", END)
    return graph.compile()


def run_graph(raw_requirement: str, scenario: str = "adhoc") -> OrchestratorState:
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
    return app.invoke(initial_state)
