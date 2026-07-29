from orchestrator.agents import sync


def test_gate4_passes_when_tests_pass_and_docs_complete():
    state = {
        "test_results": [{"name": "n", "passed": True, "detail": "", "executed": True}],
        "doc_diffs": [{"path": "p", "diff": "d", "summary": "s", "applied": True}],
    }
    result = sync.run_gate4(state)

    [entry] = result["gate_log"]
    assert entry["gate_id"] == "gate_4"
    assert entry["passed"] is True


def test_gate4_fails_when_tests_fail():
    state = {
        "test_results": [{"name": "n", "passed": False, "detail": "", "executed": True}],
        "doc_diffs": [{"path": "p", "diff": "d", "summary": "s", "applied": True}],
    }
    result = sync.run_gate4(state)

    [entry] = result["gate_log"]
    assert entry["passed"] is False
    assert "failed/missing" in entry["detail"]


def test_gate4_fails_when_docs_missing():
    state = {
        "test_results": [{"name": "n", "passed": True, "detail": "", "executed": True}],
        "doc_diffs": [],
    }
    result = sync.run_gate4(state)

    [entry] = result["gate_log"]
    assert entry["passed"] is False
    assert "docs: missing" in entry["detail"]


def test_gate4_fails_when_test_results_missing():
    state = {"doc_diffs": [{"path": "p", "diff": "d", "summary": "s", "applied": True}]}
    result = sync.run_gate4(state)

    [entry] = result["gate_log"]
    assert entry["passed"] is False
