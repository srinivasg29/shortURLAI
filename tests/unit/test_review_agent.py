from app.config import get_settings
from orchestrator.agents import review


def _state(gate_log):
    return {
        "normalized_spec": "spec",
        "code_diffs": [],
        "test_results": [],
        "doc_diffs": [],
        "gate_log": gate_log,
    }


def test_auto_approve_passes_when_gates_3_and_4_passed(monkeypatch):
    monkeypatch.setattr(review, "is_live", lambda: False)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    gate_log = [
        {"gate_id": "gate_3", "passed": True, "node": "", "approver": "", "entry_criteria": "",
         "exit_criteria": "", "timestamp": "", "detail": ""},
        {"gate_id": "gate_4", "passed": True, "node": "", "approver": "", "entry_criteria": "",
         "exit_criteria": "", "timestamp": "", "detail": ""},
    ]
    result = review.run(_state(gate_log))

    [entry] = result["gate_log"]
    assert entry["gate_id"] == "gate_5"
    assert entry["passed"] is True
    assert entry["approver"] == "system:auto_approve"
    assert result["llm_mode"] == "mock"

    get_settings.cache_clear()


def test_auto_approve_fails_closed_when_gate_4_failed(monkeypatch):
    monkeypatch.setattr(review, "is_live", lambda: False)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    gate_log = [
        {"gate_id": "gate_3", "passed": True, "node": "", "approver": "", "entry_criteria": "",
         "exit_criteria": "", "timestamp": "", "detail": ""},
        {"gate_id": "gate_4", "passed": False, "node": "", "approver": "", "entry_criteria": "",
         "exit_criteria": "", "timestamp": "", "detail": ""},
    ]
    result = review.run(_state(gate_log))

    [entry] = result["gate_log"]
    assert entry["passed"] is False
    assert entry["approver"] == "system:auto_approve"

    get_settings.cache_clear()


def test_auto_approve_fails_closed_when_gates_3_4_missing(monkeypatch):
    monkeypatch.setattr(review, "is_live", lambda: False)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    result = review.run(_state([]))

    [entry] = result["gate_log"]
    assert entry["passed"] is False

    get_settings.cache_clear()


def test_live_mode_uses_llm_summary(monkeypatch):
    monkeypatch.setattr(review, "is_live", lambda: True)
    monkeypatch.setattr(review, "call_llm", lambda *a, **k: "Looks solid, ship it.")
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    result = review.run(_state([]))

    assert "llm_mode" not in result
    assert "Looks solid" in result["gate_log"][0]["detail"]

    get_settings.cache_clear()


def test_live_mode_falls_back_when_llm_raises(monkeypatch):
    monkeypatch.setattr(review, "is_live", lambda: True)
    monkeypatch.setattr(
        review, "call_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    result = review.run(_state([]))

    assert result["llm_mode"] == "mock"

    get_settings.cache_clear()


def test_live_mode_falls_back_when_llm_returns_blank(monkeypatch):
    monkeypatch.setattr(review, "is_live", lambda: True)
    monkeypatch.setattr(review, "call_llm", lambda *a, **k: "   ")
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    result = review.run(_state([]))

    assert result["llm_mode"] == "mock"

    get_settings.cache_clear()
