import json

import orchestrator.agents.architecture as architecture_module
import orchestrator.agents.planning as planning_module
import orchestrator.agents.requirement as requirement_module
from app.config import get_settings
from orchestrator.graph import resume_run, start_run


def _force_mock(monkeypatch) -> None:
    monkeypatch.setattr(requirement_module, "is_live", lambda: False)
    monkeypatch.setattr(planning_module, "is_live", lambda: False)
    monkeypatch.setattr(architecture_module, "is_live", lambda: False)


def _use_audit_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit_log.jsonl"))
    get_settings.cache_clear()


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

    assert [g["gate_id"] for g in result["gate_log"]] == ["gate_0", "gate_1", "gate_2"]
    assert all(g["passed"] for g in result["gate_log"])
    assert result["gate_log"][2]["approver"] == "system:auto_approve"

    task_ids = {t["id"] for t in result["task_graph"]["tasks"]}
    assert task_ids == {"design", "implement", "test", "document", "review"}

    [decision] = {d["approved_by"] for d in result["architecture_decisions"]}
    assert decision == "system:auto_approve"

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


def test_resume_run_with_approval_completes_gate_2(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "0")
    _use_audit_log(tmp_path, monkeypatch)

    paused = start_run("Add rate limiting to POST /api/shorten.", scenario="ambiguous")
    final = resume_run(
        paused["run_id"],
        {"approved": True, "approver": "human:reviewer", "comment": "looks good"},
    )

    assert "__interrupt__" not in final
    assert [g["gate_id"] for g in final["gate_log"]] == ["gate_0", "gate_1", "gate_2"]
    gate_2 = final["gate_log"][2]
    assert gate_2["passed"] is True
    assert gate_2["approver"] == "human:reviewer"
    assert all(d["approved_by"] == "human:reviewer" for d in final["architecture_decisions"])

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
    assert any(e["type"] == "gate" and e["gate_id"] == "gate_0" for e in events)
    assert any(e["type"] == "gate" and e["gate_id"] == "gate_1" for e in events)
    assert any(e["type"] == "gate" and e["gate_id"] == "gate_2" for e in events)

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
