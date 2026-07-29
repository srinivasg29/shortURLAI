import json

from orchestrator import metrics


def _events(*rows: dict) -> list[dict]:
    return list(rows)


def test_load_events_returns_empty_list_when_file_missing(tmp_path):
    assert metrics.load_events(tmp_path / "does_not_exist.jsonl") == []


def test_load_events_parses_jsonl(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"a": 1}\n{"b": 2}\n\n', encoding="utf-8")

    events = metrics.load_events(path)

    assert events == [{"a": 1}, {"b": 2}]


def test_group_by_run_ignores_events_without_run_id():
    events = _events(
        {"type": "gate", "run_id": "r1"},
        {"type": "llm_retry"},
        {"type": "gate", "run_id": "r2"},
    )
    grouped = metrics.group_by_run(events)

    assert set(grouped.keys()) == {"r1", "r2"}


def test_success_rate_excludes_safe_stopped_runs():
    events = _events(
        {"type": "gate", "run_id": "r1"},
        {"type": "gate", "run_id": "r2"},
        {"type": "safe_stop", "run_id": "r2"},
    )
    assert metrics.success_rate(events) == 0.5


def test_success_rate_is_zero_with_no_runs():
    assert metrics.success_rate([]) == 0.0


def test_retry_frequency_by_node_counts_per_node():
    events = _events(
        {"type": "llm_retry", "node": "planning_agent"},
        {"type": "llm_retry", "node": "planning_agent"},
        {"type": "llm_retry", "node": "coding_agent"},
        {"type": "gate", "run_id": "r1"},
    )
    assert metrics.retry_frequency_by_node(events) == {
        "planning_agent": 2,
        "coding_agent": 1,
    }


def test_rollback_stats_computes_rate():
    events = _events(
        {"type": "safe_stop", "rollback": "reverted app/x.py"},
        {"type": "safe_stop", "rollback": None},
    )
    stats = metrics.rollback_stats(events)

    assert stats == {"safe_stop_count": 2, "rollback_count": 1, "rollback_rate": 0.5}


def test_rollback_stats_with_no_safe_stops():
    assert metrics.rollback_stats([]) == {
        "safe_stop_count": 0,
        "rollback_count": 0,
        "rollback_rate": 0.0,
    }


def test_mean_time_to_resolution_matches_safe_stop_to_resume_gap():
    events = _events(
        {"type": "safe_stop", "run_id": "r1", "timestamp": "2026-01-01T00:00:00+00:00"},
        {"type": "gate_resume", "run_id": "r1", "timestamp": "2026-01-01T00:05:00+00:00"},
    )
    assert metrics.mean_time_to_resolution_seconds(events) == 300.0


def test_mean_time_to_resolution_is_none_without_any_resolution():
    events = _events({"type": "safe_stop", "run_id": "r1", "timestamp": "2026-01-01T00:00:00+00:00"})
    assert metrics.mean_time_to_resolution_seconds(events) is None


def test_latency_breakdown_splits_human_wait_from_automated_time():
    events = _events(
        {"type": "run_start", "run_id": "r1", "timestamp": "2026-01-01T00:00:00+00:00"},
        {"type": "gate", "run_id": "r1", "timestamp": "2026-01-01T00:00:01+00:00"},
        # human takes 60s to resume
        {"type": "gate_resume", "run_id": "r1", "timestamp": "2026-01-01T00:01:01+00:00"},
        {"type": "gate", "run_id": "r1", "timestamp": "2026-01-01T00:01:02+00:00"},
    )
    breakdown = metrics.latency_breakdown_by_run(events)["r1"]

    assert breakdown["total_seconds"] == 62.0
    assert breakdown["human_wait_seconds"] == 60.0
    assert breakdown["automated_seconds"] == 2.0


def test_llm_latency_by_node_averages_successful_calls_only():
    events = _events(
        {"type": "llm_call", "node": "coding_agent", "success": True, "latency_ms": 100},
        {"type": "llm_call", "node": "coding_agent", "success": True, "latency_ms": 300},
        {"type": "llm_call", "node": "coding_agent", "success": False, "latency_ms": 50},
    )
    result = metrics.llm_latency_by_node(events)

    assert result == {"coding_agent": {"count": 2, "avg_latency_ms": 200.0}}


def test_run_timeline_filters_and_sorts_by_timestamp():
    events = _events(
        {"type": "gate", "run_id": "r1", "timestamp": "2026-01-01T00:00:02+00:00"},
        {"type": "run_start", "run_id": "r1", "timestamp": "2026-01-01T00:00:00+00:00"},
        {"type": "gate", "run_id": "r2", "timestamp": "2026-01-01T00:00:01+00:00"},
        {"type": "gate", "run_id": "r1", "timestamp": "2026-01-01T00:00:01+00:00"},
    )
    timeline = metrics.run_timeline("r1", events)

    assert [e["type"] for e in timeline] == ["run_start", "gate", "gate"]
    assert all(e["run_id"] == "r1" for e in timeline)


def test_run_timeline_empty_for_unknown_run():
    assert metrics.run_timeline("nope", [{"type": "gate", "run_id": "r1", "timestamp": "t"}]) == []


def test_compute_reliability_metrics_shape(tmp_path):
    path = tmp_path / "audit.jsonl"
    events = [
        {"type": "run_start", "run_id": "r1", "timestamp": "2026-01-01T00:00:00+00:00"},
        {"type": "gate", "run_id": "r1", "gate_id": "gate_0", "timestamp": "2026-01-01T00:00:01+00:00"},
    ]
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    result = metrics.compute_reliability_metrics(metrics.load_events(path))

    assert result["run_count"] == 1
    assert result["success_rate"] == 1.0
    assert "retry_frequency_by_node" in result
    assert "rollback" in result
    assert "llm_latency_ms_by_node" in result
