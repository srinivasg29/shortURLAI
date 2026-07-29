import json

import orchestrator.agents.requirement as requirement_module
from orchestrator.graph import run_requirement_intake


def test_run_requirement_intake_produces_normalized_state(tmp_path, monkeypatch):
    monkeypatch.setattr(requirement_module, "is_live", lambda: False)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit_log.jsonl"))
    from app.config import get_settings

    get_settings.cache_clear()

    result = run_requirement_intake(
        "Add a POST /api/shorten endpoint.", scenario="greenfield"
    )

    assert result["run_id"]
    assert result["scenario"] == "greenfield"
    assert result["normalized_spec"] == "Add a POST /api/shorten endpoint."
    assert result["llm_mode"] == "mock"
    assert len(result["gate_log"]) == 1
    assert result["gate_log"][0]["passed"] is True

    get_settings.cache_clear()


def test_run_requirement_intake_writes_audit_log(tmp_path, monkeypatch):
    monkeypatch.setattr(requirement_module, "is_live", lambda: False)
    audit_path = tmp_path / "audit_log.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    from app.config import get_settings

    get_settings.cache_clear()

    run_requirement_intake("Refactor the analytics click-counter.", scenario="brownfield")

    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines]

    assert any(e["type"] == "run_start" and e["scenario"] == "brownfield" for e in events)
    assert any(e["type"] == "gate" and e["gate_id"] == "gate_0" for e in events)

    get_settings.cache_clear()
