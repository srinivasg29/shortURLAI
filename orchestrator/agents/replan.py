from __future__ import annotations

from datetime import UTC, datetime

from orchestrator.state import OrchestratorState, ReplanLogEntry

MAX_REPLANS = 2


def _last_failed_gate_reason(state: OrchestratorState) -> str:
    gate_log = state.get("gate_log", [])
    last = gate_log[-1] if gate_log else None
    if last is None:
        return "unknown gate failure (no gate_log entry)"
    return f"{last['gate_id']} ({last['node']}) failed: {last['detail']}"


def run(state: OrchestratorState) -> OrchestratorState:
    """Routes back to Planning with the failure reason recorded, distinct
    from a retry: a retry re-runs the same node on the same inputs, a
    re-plan changes the task graph itself (see planning.default_task_graph's
    replan_reason handling)."""
    reason = _last_failed_gate_reason(state)
    count = state.get("replan_count", 0) + 1

    entry: ReplanLogEntry = {
        "trigger_reason": reason,
        "node_re_entered": "planning",
        "count": count,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    return {"replan_log": [entry], "replan_count": count}
