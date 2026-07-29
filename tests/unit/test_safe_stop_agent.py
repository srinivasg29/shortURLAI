import json

from app.config import get_settings
from orchestrator.agents import coding, safe_stop


def _gate(gate_id: str, node: str, detail: str, passed: bool = False) -> dict:
    return {
        "gate_id": gate_id,
        "node": node,
        "passed": passed,
        "approver": "system",
        "entry_criteria": "",
        "exit_criteria": "",
        "timestamp": "",
        "detail": detail,
    }


def test_run_auto_approve_skips_interrupt_and_sets_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_APPROVE", "1")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()

    state = {
        "gate_log": [_gate("gate_3", "coding_agent", "ruff failed")],
        "replan_count": 2,
        "code_diffs": [],
    }
    result = safe_stop.run(state)

    assert result["safe_stopped"] is True
    assert "gate_3" in result["safe_stop_reason"]
    assert "2 re-plan(s)" in result["safe_stop_reason"]

    get_settings.cache_clear()


def test_run_rolls_back_last_applied_diff(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_APPROVE", "1")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()

    target_dir = tmp_path / "app"
    target_dir.mkdir()
    target_file = target_dir / "x.py"
    target_file.write_text("after content\n", encoding="utf-8")
    monkeypatch.setattr(coding, "_repo_root", lambda: tmp_path)

    state = {
        "gate_log": [_gate("gate_3", "coding_agent", "ruff failed")],
        "replan_count": 2,
        "code_diffs": [
            {
                "path": "app/x.py",
                "diff": "d",
                "summary": "s",
                "applied": True,
                "before": "before content\n",
            }
        ],
    }
    safe_stop.run(state)

    assert target_file.read_text(encoding="utf-8") == "before content\n"

    get_settings.cache_clear()


def test_run_writes_audit_event_with_rollback_outcome(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUTO_APPROVE", "1")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    get_settings.cache_clear()

    state = {
        "gate_log": [_gate("gate_4", "gate4_sync", "tests failed")],
        "replan_count": 2,
        "code_diffs": [],
        "run_id": "run-123",
    }
    safe_stop.run(state)

    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    [event] = [e for e in events if e["type"] == "safe_stop"]
    assert event["run_id"] == "run-123"
    assert event["rollback"] is None
    assert "gate_4" in event["reason"]

    get_settings.cache_clear()


def test_run_handles_missing_gate_log(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_APPROVE", "1")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()

    result = safe_stop.run({"replan_count": 0, "code_diffs": []})

    assert result["safe_stopped"] is True
    assert "no gate_log entry found" in result["safe_stop_reason"]

    get_settings.cache_clear()
