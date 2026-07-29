import orchestrator.agents.architecture as architecture_module
import orchestrator.agents.coding as coding_module
import orchestrator.agents.documentation as documentation_module
import orchestrator.agents.planning as planning_module
import orchestrator.agents.requirement as requirement_module
import orchestrator.agents.review as review_module
import orchestrator.agents.testing as testing_module
from app.config import get_settings
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


def test_metrics_endpoint_returns_prometheus_text_with_no_runs(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()

    resp = client.get("/orchestrator/metrics")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "orchestrator_run_count 0.0" in resp.text
    assert "orchestrator_success_rate 0.0" in resp.text

    get_settings.cache_clear()


def test_metrics_endpoint_reflects_a_real_run(client, tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()

    start_run("Add a POST /api/shorten endpoint.", scenario="greenfield")

    resp = client.get("/orchestrator/metrics")

    assert "orchestrator_run_count 1.0" in resp.text
    assert "orchestrator_success_rate 1.0" in resp.text

    get_settings.cache_clear()


def test_metrics_endpoint_includes_retry_latency_and_mttr_when_present(
    client, tmp_path, monkeypatch
):
    from datetime import UTC, datetime

    from orchestrator import audit

    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()

    now = datetime.now(UTC).isoformat()
    audit.append_event(
        {"type": "llm_retry", "node": "planning_agent", "attempt": 1, "timestamp": now}
    )
    audit.append_event(
        {
            "type": "llm_call",
            "node": "coding_agent",
            "success": True,
            "latency_ms": 250,
            "timestamp": now,
        }
    )
    audit.append_event({"type": "safe_stop", "run_id": "r1", "timestamp": now})
    audit.append_event({"type": "gate_resume", "run_id": "r1", "timestamp": now})

    resp = client.get("/orchestrator/metrics")

    assert 'orchestrator_llm_retry_count{node="planning_agent"} 1.0' in resp.text
    assert 'orchestrator_llm_latency_ms_avg{node="coding_agent"} 250.0' in resp.text
    assert "orchestrator_mean_time_to_resolution_seconds 0.0" in resp.text

    get_settings.cache_clear()


def test_run_timeline_endpoint_404s_for_unknown_run(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()

    resp = client.get("/orchestrator/runs/does-not-exist")

    assert resp.status_code == 404

    get_settings.cache_clear()


def test_run_timeline_endpoint_returns_chronological_events(client, tmp_path, monkeypatch):
    _force_mock(monkeypatch)
    monkeypatch.setenv("AUTO_APPROVE", "1")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()

    result = start_run("Add a POST /api/shorten endpoint.", scenario="greenfield")

    resp = client.get(f"/orchestrator/runs/{result['run_id']}")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["type"] == "run_start"
    assert all(e["run_id"] == result["run_id"] for e in body)
    timestamps = [e["timestamp"] for e in body]
    assert timestamps == sorted(timestamps)

    get_settings.cache_clear()
