import json

import orchestrator.agents.planning as planning_module
import orchestrator.agents.requirement as requirement_module
from orchestrator.graph import run_graph


def test_run_graph_produces_normalized_state_and_task_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(requirement_module, "is_live", lambda: False)
    monkeypatch.setattr(planning_module, "is_live", lambda: False)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit_log.jsonl"))
    from app.config import get_settings

    get_settings.cache_clear()

    result = run_graph("Add a POST /api/shorten endpoint.", scenario="greenfield")

    assert result["run_id"]
    assert result["scenario"] == "greenfield"
    assert result["normalized_spec"] == "Add a POST /api/shorten endpoint."
    assert result["llm_mode"] == "mock"

    assert len(result["gate_log"]) == 2
    assert [g["gate_id"] for g in result["gate_log"]] == ["gate_0", "gate_1"]
    assert all(g["passed"] for g in result["gate_log"])

    task_ids = {t["id"] for t in result["task_graph"]["tasks"]}
    assert task_ids == {"design", "implement", "test", "document", "review"}

    get_settings.cache_clear()


def test_run_graph_writes_audit_log(tmp_path, monkeypatch):
    monkeypatch.setattr(requirement_module, "is_live", lambda: False)
    monkeypatch.setattr(planning_module, "is_live", lambda: False)
    audit_path = tmp_path / "audit_log.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    from app.config import get_settings

    get_settings.cache_clear()

    run_graph("Refactor the analytics click-counter.", scenario="brownfield")

    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines]

    assert any(e["type"] == "run_start" and e["scenario"] == "brownfield" for e in events)
    assert any(e["type"] == "gate" and e["gate_id"] == "gate_0" for e in events)
    assert any(e["type"] == "gate" and e["gate_id"] == "gate_1" for e in events)

    get_settings.cache_clear()
