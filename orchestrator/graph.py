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
    release,
    replan,
    requirement,
    review,
    safe_stop,
    sync,
    testing,
)
from orchestrator.state import OrchestratorState

MAX_REPLANS = 2


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


def _review_node(state: OrchestratorState) -> OrchestratorState:
    result = review.run(state)
    for entry in result.get("gate_log", []):
        audit.append_event({"type": "gate", **entry})
    return result


def _release_node(state: OrchestratorState) -> OrchestratorState:
    result = release.run(state)
    for entry in result.get("gate_log", []):
        audit.append_event({"type": "gate", **entry})
    return result


def _replan_node(state: OrchestratorState) -> OrchestratorState:
    result = replan.run(state)
    for entry in result.get("replan_log", []):
        audit.append_event({"type": "replan", **entry})
    return result


def _safe_stop_node(state: OrchestratorState) -> OrchestratorState:
    # safe_stop.run() logs its own audit event (reason + rollback outcome)
    # since safe_stopped/safe_stop_reason are scalar state fields, not a
    # list this wrapper can iterate the way it does for gate_log/replan_log.
    return safe_stop.run(state)


def _make_gate_router(gate_id: str):
    """Shared routing logic for the three re-plan checkpoints (Architecture
    / Gate 2, Coding / Gate 3, gate4_sync / Gate 4 standing in for Testing -
    see README for why gate4_sync is used instead of the Testing node
    directly). Returns "pass", "replan", or "safe_stop"; callers map those
    labels to actual node names via path_map."""

    def _router(state: OrchestratorState) -> str:
        matching = [g for g in state.get("gate_log", []) if g["gate_id"] == gate_id]
        passed = matching[-1]["passed"] if matching else True
        if passed:
            return "pass"
        return "replan" if state.get("replan_count", 0) < MAX_REPLANS else "safe_stop"

    return _router


def _coding_router(state: OrchestratorState) -> list[str]:
    matching = [g for g in state.get("gate_log", []) if g["gate_id"] == "gate_3"]
    passed = matching[-1]["passed"] if matching else True
    if passed:
        return ["testing", "documentation"]
    if state.get("replan_count", 0) < MAX_REPLANS:
        return ["replan_node"]
    return ["safe_stop_node"]


@lru_cache
def build_graph():
    """Compiled once and cached: the checkpointer backing the human-approval
    gates' interrupt/resume must be the same instance across a run's start
    and resume calls, since it's what holds the paused state in memory."""
    graph = StateGraph(OrchestratorState)
    graph.add_node("requirement", _requirement_node)
    graph.add_node("planning", _planning_node)
    graph.add_node("architecture", _architecture_node)
    graph.add_node("coding", _coding_node)
    graph.add_node("testing", _testing_node)
    graph.add_node("documentation", _documentation_node)
    graph.add_node("gate4_sync", _gate4_sync_node)
    graph.add_node("review", _review_node)
    graph.add_node("release", _release_node)
    graph.add_node("replan_node", _replan_node)
    graph.add_node("safe_stop_node", _safe_stop_node)

    graph.set_entry_point("requirement")
    graph.add_edge("requirement", "planning")
    graph.add_edge("planning", "architecture")

    # Gate 2 checkpoint: Architecture rejected -> re-plan (bounded) -> safe-stop.
    graph.add_conditional_edges(
        "architecture",
        _make_gate_router("gate_2"),
        {"pass": "coding", "replan": "replan_node", "safe_stop": "safe_stop_node"},
    )

    # Gate 3 checkpoint: Coding's build/static checks failed -> re-plan ->
    # safe-stop. On pass, fans out to the parallel Testing/Documentation
    # branch in the same conditional edge (a router can return a list of
    # target nodes to fan out, same as an unconditional edge pair would).
    graph.add_conditional_edges(
        "coding",
        _coding_router,
        ["testing", "documentation", "replan_node", "safe_stop_node"],
    )
    graph.add_edge("testing", "gate4_sync")
    graph.add_edge("documentation", "gate4_sync")

    # Gate 4 checkpoint (standing in for "Testing", per the plan's trigger
    # list) - tests failing is what can make gate4_sync fail, since docs
    # always trivially "complete" in this design.
    graph.add_conditional_edges(
        "gate4_sync",
        _make_gate_router("gate_4"),
        {"pass": "review", "replan": "replan_node", "safe_stop": "safe_stop_node"},
    )

    graph.add_edge("review", "release")
    graph.add_edge("release", END)

    graph.add_edge("replan_node", "planning")
    graph.add_edge("safe_stop_node", END)

    return graph.compile(checkpointer=InMemorySaver())


def start_run(raw_requirement: str, scenario: str = "adhoc") -> OrchestratorState:
    """Starts a new run. If AUTO_APPROVE is unset, this returns as soon as the
    graph hits a human gate (2, 5, 6) or a safe-stop notification — the
    returned state carries an "__interrupt__" key; call
    resume_run(state["run_id"], decision) to continue."""
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
    """Resumes a run paused at a human-approval gate or a safe-stop
    notification with the human's decision, e.g.
    {"approved": True, "approver": "human:sri", "comment": "looks good"}."""
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
