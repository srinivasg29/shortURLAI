import orchestrator.agents.architecture as architecture_module
import orchestrator.agents.coding as coding_module
import orchestrator.agents.documentation as documentation_module
import orchestrator.agents.planning as planning_module
import orchestrator.agents.requirement as requirement_module
import orchestrator.agents.review as review_module
import orchestrator.agents.testing as testing_module
from app.config import get_settings
from orchestrator import metrics
from orchestrator.graph import start_run


def _force_mock(monkeypatch) -> None:
    for mod in (
        requirement_module,
        planning_module,
        architecture_module,
        coding_module,
        testing_module,
        documentation_module,
        review_module,
    ):
        monkeypatch.setattr(mod, "is_live", lambda: False)


def test_metrics_reflect_a_real_successful_run(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    get_settings.cache_clear()

    result = start_run("Add a POST /api/shorten endpoint.", scenario="greenfield")
    assert result["released"] is True

    computed = metrics.compute_reliability_metrics(metrics.load_events(audit_path))

    assert computed["run_count"] == 1
    assert computed["success_rate"] == 1.0
    assert computed["rollback"]["safe_stop_count"] == 0
    assert computed["avg_end_to_end_seconds"] >= 0

    get_settings.cache_clear()


def test_metrics_reflect_a_safe_stopped_run(tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    get_settings.cache_clear()

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
    assert result["safe_stopped"] is True

    computed = metrics.compute_reliability_metrics(metrics.load_events(audit_path))

    assert computed["run_count"] == 1
    assert computed["success_rate"] == 0.0
    assert computed["rollback"]["safe_stop_count"] == 1

    get_settings.cache_clear()
