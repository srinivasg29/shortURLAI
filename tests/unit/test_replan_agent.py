from orchestrator.agents import replan


def _gate(gate_id: str, node: str, detail: str) -> dict:
    return {
        "gate_id": gate_id,
        "node": node,
        "passed": False,
        "approver": "system",
        "entry_criteria": "",
        "exit_criteria": "",
        "timestamp": "",
        "detail": detail,
    }


def test_run_records_trigger_reason_from_last_gate():
    state = {"gate_log": [_gate("gate_3", "coding_agent", "ruff failed")], "replan_count": 0}
    result = replan.run(state)

    [entry] = result["replan_log"]
    assert entry["node_re_entered"] == "planning"
    assert entry["count"] == 1
    assert "gate_3" in entry["trigger_reason"]
    assert "ruff failed" in entry["trigger_reason"]
    assert result["replan_count"] == 1


def test_run_increments_existing_replan_count():
    state = {"gate_log": [_gate("gate_2", "architecture_agent", "rejected")], "replan_count": 1}
    result = replan.run(state)

    assert result["replan_count"] == 2
    assert result["replan_log"][0]["count"] == 2


def test_run_handles_missing_gate_log_gracefully():
    result = replan.run({"replan_count": 0})

    assert result["replan_count"] == 1
    assert "unknown" in result["replan_log"][0]["trigger_reason"]
