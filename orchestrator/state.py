from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


class GateLogEntry(TypedDict):
    gate_id: str
    node: str
    passed: bool
    approver: str
    entry_criteria: str
    exit_criteria: str
    timestamp: str
    detail: str


class ReplanLogEntry(TypedDict):
    trigger_reason: str
    node_re_entered: str
    count: int
    timestamp: str


class ArchitectureDecision(TypedDict):
    decision: str
    rationale: str
    approved_by: str
    timestamp: str


class CodeDiff(TypedDict):
    path: str
    diff: str
    summary: str
    applied: bool


class TestResult(TypedDict):
    name: str
    passed: bool
    detail: str
    executed: bool


class DocDiff(TypedDict):
    path: str
    diff: str
    summary: str
    applied: bool


class OrchestratorState(TypedDict, total=False):
    """Single typed state object threaded through every LangGraph node.

    List-valued fields use `operator.add` as their reducer so that nodes
    append rather than overwrite, per the plan's decision-lineage
    requirement — this also lets parallel branches (Testing/Documentation)
    each contribute to the same field without clobbering the other's writes.
    """

    run_id: str
    scenario: str
    raw_requirement: str

    requirement_summary: str
    identified_ambiguities: list[str]
    normalized_spec: str

    task_graph: dict[str, Any]

    architecture_decisions: Annotated[list[ArchitectureDecision], operator.add]
    code_diffs: Annotated[list[CodeDiff], operator.add]
    test_results: Annotated[list[TestResult], operator.add]
    doc_diffs: Annotated[list[DocDiff], operator.add]

    gate_log: Annotated[list[GateLogEntry], operator.add]
    replan_log: Annotated[list[ReplanLogEntry], operator.add]

    llm_mode: Literal["live", "mock"]
    replan_count: int
    safe_stopped: bool
    safe_stop_reason: str
    released: bool
