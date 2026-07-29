import json

import pytest

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


def test_resume_run_with_rejection_at_gate_2_triggers_replan(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    paused = start_run("Add rate limiting to POST /api/shorten.", scenario="ambiguous")
    after_rejection = resume_run(
        paused["run_id"],
        {"approved": False, "approver": "human:reviewer", "comment": "needs rework"},
    )

    gate_2 = after_rejection["gate_log"][2]
    assert gate_2["passed"] is False
    assert after_rejection["architecture_decisions"][0]["approved_by"] == (
        "rejected_by:human:reviewer"
    )
    # Rejection routes back to Planning (bounded), not straight through to
    # Coding - the graph pauses at a *fresh* Gate 2 proposal instead of
    # continuing downstream with a rejected design.
    assert after_rejection["__interrupt__"][0].value["gate_id"] == "gate_2"
    # gate_0, gate_1, gate_2 from the first attempt, then a second gate_1
    # from re-entering Planning; Architecture is paused on the fresh Gate 2
    # proposal, so it hasn't logged a second gate_2 entry yet.
    assert [g["gate_id"] for g in after_rejection["gate_log"]] == [
        "gate_0",
        "gate_1",
        "gate_2",
        "gate_1",
    ]

    [replan_entry] = after_rejection["replan_log"]
    assert replan_entry["count"] == 1
    assert replan_entry["node_re_entered"] == "planning"
    assert "gate_2" in replan_entry["trigger_reason"]

    # Planning incorporated the rejection into the re-plan, per
    # planning.default_task_graph's replan_reason handling.
    task_ids = {t["id"] for t in after_rejection["task_graph"]["tasks"]}
    assert "remediate" in task_ids

    get_settings.cache_clear()


def test_repeated_gate_2_rejection_reaches_safe_stop_after_max_replans(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    state = start_run("Add rate limiting to POST /api/shorten.", scenario="ambiguous")
    for _ in range(3):
        assert state["__interrupt__"][0].value["gate_id"] == "gate_2"
        state = resume_run(
            state["run_id"],
            {"approved": False, "approver": "human:reviewer", "comment": "still not it"},
        )

    # Third rejection exhausts MAX_REPLANS (2) -> safe-stop notification
    # instead of a fourth Gate 2 pause.
    assert state["__interrupt__"][0].value["type"] == "safe_stop"
    assert "gate_2" in state["__interrupt__"][0].value["reason"]
    assert state["replan_count"] == 2
    assert len(state["replan_log"]) == 2

    final = resume_run(state["run_id"], {"acknowledged": True})
    assert "__interrupt__" not in final
    assert final["safe_stopped"] is True

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


def test_persistent_gate4_failure_replans_then_safe_stops(tmp_path, monkeypatch):
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

    gate_4_entries = [g for g in result["gate_log"] if g["gate_id"] == "gate_4"]
    # Initial attempt + 2 re-plans = 3 total attempts before MAX_REPLANS
    # is exhausted and the graph safe-stops instead of reaching Gate 5.
    assert len(gate_4_entries) == 3
    assert all(not g["passed"] for g in gate_4_entries)
    assert all("tests: failed/missing" in g["detail"] for g in gate_4_entries)
    # Documentation branch still ran independently of Testing's failure,
    # every time through the loop.
    assert len(result["doc_diffs"]) == 3

    assert result["replan_count"] == 2
    assert [r["node_re_entered"] for r in result["replan_log"]] == ["planning", "planning"]
    assert result["safe_stopped"] is True
    assert "gate_4" in result["safe_stop_reason"]

    # Never reached the Review/Release gates in this run.
    assert not any(g["gate_id"] in ("gate_5", "gate_6") for g in result["gate_log"])
    assert "released" not in result

    get_settings.cache_clear()


def test_safe_stop_rolls_back_last_applied_code_change(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    _use_audit_log(tmp_path, monkeypatch)

    target_dir = tmp_path / "app"
    target_dir.mkdir()
    target_file = target_dir / "shorten.py"
    before_content = "def before():\n    pass\n"
    target_file.write_text(before_content, encoding="utf-8")
    monkeypatch.setattr(coding_module, "_repo_root", lambda: tmp_path)

    calls = {"n": 0}

    def fake_coding_run(state):
        calls["n"] += 1
        if calls["n"] == 1:
            # First attempt actually applies a change (like a real live-mode
            # edit would) before its own Gate 3 check fails.
            target_file.write_text("def after():\n    pass\n", encoding="utf-8")
            diff = {
                "path": "app/shorten.py",
                "diff": "d",
                "summary": "applied",
                "applied": True,
                "before": before_content,
            }
        else:
            diff = {
                "path": "UNSPECIFIED",
                "diff": "",
                "summary": "",
                "applied": False,
                "before": "",
            }
        gate_entry = {
            "gate_id": "gate_3",
            "node": "coding_agent",
            "passed": False,
            "approver": "system",
            "entry_criteria": "",
            "exit_criteria": "",
            "timestamp": "t",
            "detail": "forced failure",
        }
        return {"code_diffs": [diff], "gate_log": [gate_entry]}

    monkeypatch.setattr(coding_module, "run", fake_coding_run)

    result = start_run("Add a POST /api/shorten endpoint.", scenario="greenfield")

    assert result["safe_stopped"] is True
    # Rolled back to the pre-change content, not left with the first
    # attempt's unresolved (Gate-3-failing) edit sitting on disk.
    assert target_file.read_text(encoding="utf-8") == before_content

    get_settings.cache_clear()


def test_safe_stop_interrupts_with_reason_when_not_auto_approved(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    monkeypatch.setattr(
        coding_module,
        "run",
        lambda state: {
            "code_diffs": [
                {"path": "UNSPECIFIED", "diff": "", "summary": "", "applied": False, "before": ""}
            ],
            "gate_log": [
                {
                    "gate_id": "gate_3",
                    "node": "coding_agent",
                    "passed": False,
                    "approver": "system",
                    "entry_criteria": "",
                    "exit_criteria": "",
                    "timestamp": "t",
                    "detail": "forced failure",
                }
            ],
        },
    )

    state = start_run("Add a POST /api/shorten endpoint.", scenario="greenfield")
    # Every re-plan re-enters Architecture, which also pauses interactively
    # at Gate 2 - drive through those until the safe_stop notification
    # replaces what would otherwise be a fourth Gate 2 pause.
    payload = None
    for _ in range(5):
        assert "__interrupt__" in state
        payload = state["__interrupt__"][0].value
        if payload.get("type") == "safe_stop":
            break
        assert payload["gate_id"] == "gate_2"
        state = resume_run(state["run_id"], {"approved": True, "approver": "human:architect"})
    else:
        pytest.fail("never reached the safe_stop interrupt")

    assert "gate_3" in payload["reason"]
    assert state["replan_count"] == 2

    final = resume_run(state["run_id"], {"acknowledged": True})
    assert "__interrupt__" not in final
    assert final["safe_stopped"] is True

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
