import json

import orchestrator.agents.architecture as architecture_module
import orchestrator.agents.coding as coding_module
import orchestrator.agents.documentation as documentation_module
import orchestrator.agents.planning as planning_module
import orchestrator.agents.requirement as requirement_module
import orchestrator.agents.review as review_module
import orchestrator.agents.testing as testing_module
from app.config import get_settings
from orchestrator.graph import resume_run, start_run


def _force_mock(monkeypatch) -> None:
    monkeypatch.setattr(requirement_module, "is_live", lambda: False)
    monkeypatch.setattr(planning_module, "is_live", lambda: False)
    monkeypatch.setattr(architecture_module, "is_live", lambda: False)
    monkeypatch.setattr(coding_module, "is_live", lambda: False)
    monkeypatch.setattr(testing_module, "is_live", lambda: False)
    monkeypatch.setattr(documentation_module, "is_live", lambda: False)
    monkeypatch.setattr(review_module, "is_live", lambda: False)


def _use_audit_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit_log.jsonl"))
    get_settings.cache_clear()


ALL_GATE_IDS = ["gate_0", "gate_1", "gate_2", "gate_3", "gate_4", "gate_5", "gate_6"]


def test_start_run_auto_approve_completes_end_to_end(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    _use_audit_log(tmp_path, monkeypatch)

    result = start_run("Add a POST /api/shorten endpoint.", scenario="greenfield")

    assert "__interrupt__" not in result
    assert result["run_id"]
    assert result["scenario"] == "greenfield"
    assert result["normalized_spec"] == "Add a POST /api/shorten endpoint."
    assert result["llm_mode"] == "mock"

    assert [g["gate_id"] for g in result["gate_log"]] == ALL_GATE_IDS
    assert all(g["passed"] for g in result["gate_log"])
    assert result["gate_log"][2]["approver"] == "system:auto_approve"
    assert result["released"] is True

    task_ids = {t["id"] for t in result["task_graph"]["tasks"]}
    assert task_ids == {"design", "implement", "test", "document", "review"}

    [decision] = {d["approved_by"] for d in result["architecture_decisions"]}
    assert decision == "system:auto_approve"

    # Mock mode never touches the real filesystem: proposal-only diff.
    [diff] = result["code_diffs"]
    assert diff["applied"] is False
    assert diff["path"] == "app/routers/shorten.py"

    # Both parallel branches (Testing, Documentation) contributed to state -
    # proof the operator.add reducers merged both branches' writes rather
    # than one clobbering the other.
    [test_result] = result["test_results"]
    assert test_result["executed"] is False
    [doc_diff] = result["doc_diffs"]
    assert doc_diff["applied"] is False

    gate_4 = result["gate_log"][4]
    assert gate_4["node"] == "gate4_sync"
    assert "tests: passed" in gate_4["detail"]
    assert "docs: complete" in gate_4["detail"]

    get_settings.cache_clear()


def test_start_run_without_auto_approve_pauses_at_gate_2(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    result = start_run("Add rate limiting to POST /api/shorten.", scenario="ambiguous")

    assert "__interrupt__" in result
    [interrupt] = result["__interrupt__"]
    assert interrupt.value["gate_id"] == "gate_2"
    assert interrupt.value["proposals"]
    # Nodes after the interrupt haven't run yet.
    assert result["architecture_decisions"] == []
    assert [g["gate_id"] for g in result["gate_log"]] == ["gate_0", "gate_1"]

    get_settings.cache_clear()


def test_full_interactive_run_pauses_at_every_human_gate_in_order(tmp_path, monkeypatch):
    """Drives a run through all three human checkpoints (Gate 2, 5, 6) via
    separate resume_run calls, proving the same checkpointer/thread_id
    correctly resumes from wherever the graph is currently paused - not
    just the first interrupt it ever hit."""
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    state = start_run("Add rate limiting to POST /api/shorten.", scenario="ambiguous")
    assert state["__interrupt__"][0].value["gate_id"] == "gate_2"

    state = resume_run(
        state["run_id"], {"approved": True, "approver": "human:architect", "comment": "ok"}
    )
    assert state["__interrupt__"][0].value["gate_id"] == "gate_5"
    assert [g["gate_id"] for g in state["gate_log"]] == [
        "gate_0",
        "gate_1",
        "gate_2",
        "gate_3",
        "gate_4",
    ]

    state = resume_run(
        state["run_id"], {"approved": True, "approver": "human:reviewer", "comment": "lgtm"}
    )
    assert state["__interrupt__"][0].value["gate_id"] == "gate_6"
    assert [g["gate_id"] for g in state["gate_log"]] == [
        "gate_0",
        "gate_1",
        "gate_2",
        "gate_3",
        "gate_4",
        "gate_5",
    ]
    assert "released" not in state

    final = resume_run(
        state["run_id"], {"approved": True, "approver": "human:releaser", "comment": "go"}
    )
    assert "__interrupt__" not in final
    assert [g["gate_id"] for g in final["gate_log"]] == ALL_GATE_IDS
    assert final["released"] is True
    assert final["gate_log"][6]["approver"] == "human:releaser"

    get_settings.cache_clear()


def test_release_readiness_blocks_when_reviewer_rejects(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    state = start_run("Add rate limiting to POST /api/shorten.", scenario="ambiguous")
    state = resume_run(state["run_id"], {"approved": True, "approver": "human:architect"})
    assert state["__interrupt__"][0].value["gate_id"] == "gate_5"

    state = resume_run(
        state["run_id"],
        {"approved": False, "approver": "human:reviewer", "comment": "not ready"},
    )
    assert state["__interrupt__"][0].value["gate_id"] == "gate_6"
    # Release Readiness Agent's own checklist sees the Gate 5 failure and
    # surfaces it to the human, rather than hiding it.
    assert state["__interrupt__"][0].value["ready"] is False
    assert "gate_5" in state["__interrupt__"][0].value["checklist"]

    final = resume_run(state["run_id"], {"approved": True, "approver": "human:releaser"})
    # The human can still override and release anyway - that's their call,
    # not the system's to make silently.
    assert final["released"] is True
    assert final["gate_log"][5]["passed"] is False

    get_settings.cache_clear()


def test_resume_run_with_rejection_fails_gate_2(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    paused = start_run("Add rate limiting to POST /api/shorten.", scenario="ambiguous")
    final = resume_run(
        paused["run_id"],
        {"approved": False, "approver": "human:reviewer", "comment": "needs rework"},
    )

    gate_2 = final["gate_log"][2]
    assert gate_2["passed"] is False
    assert final["architecture_decisions"][0]["approved_by"] == "rejected_by:human:reviewer"
    # Gate 2 rejection doesn't yet halt the graph - conditional routing back
    # to Planning on rejection is wired in Phase 11 (re-planning). For now
    # the graph runs straight through to Coding, Testing, and Documentation,
    # pausing next at Gate 5 same as any other run.
    assert [g["gate_id"] for g in final["gate_log"]] == [
        "gate_0",
        "gate_1",
        "gate_2",
        "gate_3",
        "gate_4",
    ]
    assert final["__interrupt__"][0].value["gate_id"] == "gate_5"

    get_settings.cache_clear()


def test_resume_run_accepts_plain_boolean_decision(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    paused = start_run("Add rate limiting to POST /api/shorten.", scenario="ambiguous")
    final = resume_run(paused["run_id"], True)

    gate_2 = final["gate_log"][2]
    assert gate_2["passed"] is True
    assert gate_2["approver"] == "human"
    assert all(d["approved_by"] == "human" for d in final["architecture_decisions"])

    get_settings.cache_clear()


def test_resume_run_accepts_plain_boolean_decision_at_every_human_gate(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    state = start_run("Add rate limiting to POST /api/shorten.", scenario="ambiguous")
    state = resume_run(state["run_id"], True)  # Gate 2
    state = resume_run(state["run_id"], True)  # Gate 5
    final = resume_run(state["run_id"], True)  # Gate 6

    assert [g["gate_id"] for g in final["gate_log"]] == ALL_GATE_IDS
    assert all(g["passed"] for g in final["gate_log"])
    assert all(
        g["approver"] == "human" for g in final["gate_log"] if g["gate_id"] in ("gate_5", "gate_6")
    )
    assert final["released"] is True

    get_settings.cache_clear()


def test_start_run_writes_audit_log(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    audit_path = tmp_path / "audit_log.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    get_settings.cache_clear()

    start_run("Refactor the analytics click-counter.", scenario="brownfield")

    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines]

    assert any(e["type"] == "run_start" and e["scenario"] == "brownfield" for e in events)
    for gate_id in ALL_GATE_IDS:
        assert any(e["type"] == "gate" and e["gate_id"] == gate_id for e in events)
    assert any(e["type"] == "code_diff" for e in events)
    assert any(e["type"] == "test_result" for e in events)
    assert any(e["type"] == "doc_diff" for e in events)

    get_settings.cache_clear()


def test_gate4_fails_when_testing_branch_fails_even_if_docs_complete(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    _use_audit_log(tmp_path, monkeypatch)

    monkeypatch.setattr(
        testing_module,
        "run",
        lambda state: {
            "test_results": [
                {"name": "forced_failure", "passed": False, "detail": "boom", "executed": True}
            ]
        },
    )

    result = start_run("Add a POST /api/shorten endpoint.", scenario="greenfield")

    gate_4 = next(g for g in result["gate_log"] if g["gate_id"] == "gate_4")
    assert gate_4["passed"] is False
    assert "tests: failed/missing" in gate_4["detail"]
    assert "docs: complete" in gate_4["detail"]
    # Documentation branch still ran independently of Testing's failure.
    assert result["doc_diffs"]
    # Gate 4's failure propagates into Gate 5's auto-approve check, which
    # fails closed rather than rubber-stamping past a failed sync gate.
    gate_5 = next(g for g in result["gate_log"] if g["gate_id"] == "gate_5")
    assert gate_5["passed"] is False
    # ...which in turn blocks Gate 6's auto-approve.
    gate_6 = next(g for g in result["gate_log"] if g["gate_id"] == "gate_6")
    assert gate_6["passed"] is False
    assert result["released"] is False

    get_settings.cache_clear()


def test_resume_run_writes_gate_resume_audit_event(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    audit_path = tmp_path / "audit_log.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    get_settings.cache_clear()

    paused = start_run("Add rate limiting.", scenario="ambiguous")
    resume_run(paused["run_id"], {"approved": True, "approver": "human:x"})

    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines]

    assert any(e["type"] == "gate_resume" and e["run_id"] == paused["run_id"] for e in events)

    get_settings.cache_clear()
