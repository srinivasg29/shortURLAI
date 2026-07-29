from app.config import get_settings
from orchestrator.agents import release


def _gate(gate_id: str, passed: bool) -> dict:
    return {
        "gate_id": gate_id,
        "passed": passed,
        "node": "",
        "approver": "",
        "entry_criteria": "",
        "exit_criteria": "",
        "timestamp": "",
        "detail": "",
    }


def test_auto_approve_releases_when_all_gates_passed(monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    state = {"gate_log": [_gate("gate_0", True), _gate("gate_5", True)]}
    result = release.run(state)

    [entry] = result["gate_log"]
    assert entry["gate_id"] == "gate_6"
    assert entry["passed"] is True
    assert entry["approver"] == "system:auto_approve"
    assert result["released"] is True

    get_settings.cache_clear()


def test_auto_approve_blocks_release_when_a_prior_gate_failed(monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    state = {"gate_log": [_gate("gate_0", True), _gate("gate_5", False)]}
    result = release.run(state)

    [entry] = result["gate_log"]
    assert entry["passed"] is False
    assert "gate_5" in entry["detail"]
    assert result["released"] is False

    get_settings.cache_clear()


def test_auto_approve_releases_with_empty_gate_log(monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE", "1")
    get_settings.cache_clear()

    result = release.run({"gate_log": []})

    assert result["gate_log"][0]["passed"] is True
    assert result["released"] is True

    get_settings.cache_clear()
