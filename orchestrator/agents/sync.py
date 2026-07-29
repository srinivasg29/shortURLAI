from __future__ import annotations

from datetime import UTC, datetime

from orchestrator.state import GateLogEntry, OrchestratorState


def run_gate4(state: OrchestratorState) -> OrchestratorState:
    """Evaluates Gate 4 after the parallel Testing/Documentation branches
    both complete: tests pass AND docs are complete. Runs once, after the
    fan-in, rather than being logged separately by either branch - this is
    what makes it a genuine synchronization gate rather than two
    independent checks."""
    test_results = state.get("test_results", [])
    doc_diffs = state.get("doc_diffs", [])

    tests_passed = bool(test_results) and test_results[-1]["passed"]
    docs_complete = bool(doc_diffs)
    passed = tests_passed and docs_complete

    gate_entry: GateLogEntry = {
        "gate_id": "gate_4",
        "node": "gate4_sync",
        "passed": passed,
        "approver": "system",
        "entry_criteria": "testing_agent and documentation_agent both completed",
        "exit_criteria": "SYNC: tests pass AND docs complete",
        "timestamp": datetime.now(UTC).isoformat(),
        "detail": (
            f"tests: {'passed' if tests_passed else 'failed/missing'}; "
            f"docs: {'complete' if docs_complete else 'missing'}"
        ),
    }
    return {"gate_log": [gate_entry]}
