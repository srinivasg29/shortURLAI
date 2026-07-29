from app.config import get_settings
from orchestrator.agents import architecture


def test_default_proposals_returns_decision_and_rationale():
    proposals = architecture.default_proposals("some spec")
    assert len(proposals) >= 1
    for p in proposals:
        assert p["decision"]
        assert p["rationale"]


def test_run_auto_approve_skips_interrupt_and_passes_gate(monkeypatch):
    monkeypatch.setattr(architecture, "is_live", lambda: False)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    result = architecture.run({"normalized_spec": "Add vanity aliases."})

    [entry] = result["gate_log"]
    assert entry["gate_id"] == "gate_2"
    assert entry["passed"] is True
    assert entry["approver"] == "system:auto_approve"
    assert all(d["approved_by"] == "system:auto_approve" for d in result["architecture_decisions"])
    assert result["llm_mode"] == "mock"

    get_settings.cache_clear()


def test_run_auto_approve_omits_llm_mode_when_live_succeeds(monkeypatch):
    monkeypatch.setattr(architecture, "is_live", lambda: True)
    monkeypatch.setattr(
        architecture,
        "call_llm",
        lambda *a, **k: '{"decisions": [{"decision": "d", "rationale": "r"}]}',
    )
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    result = architecture.run({"normalized_spec": "spec"})

    assert "llm_mode" not in result
    assert result["architecture_decisions"][0]["decision"] == "d"

    get_settings.cache_clear()


def test_run_auto_approve_falls_back_when_live_call_raises(monkeypatch):
    monkeypatch.setattr(architecture, "is_live", lambda: True)
    monkeypatch.setattr(
        architecture, "call_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    result = architecture.run({"normalized_spec": "spec"})

    assert result["llm_mode"] == "mock"
    assert result["architecture_decisions"]

    get_settings.cache_clear()


def test_run_auto_approve_falls_back_when_live_response_has_no_decisions(monkeypatch):
    monkeypatch.setattr(architecture, "is_live", lambda: True)
    monkeypatch.setattr(architecture, "call_llm", lambda *a, **k: '{"decisions": []}')
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    result = architecture.run({"normalized_spec": "spec"})

    assert result["llm_mode"] == "mock"
    assert result["architecture_decisions"]

    get_settings.cache_clear()
