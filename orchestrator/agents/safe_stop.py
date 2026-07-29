from __future__ import annotations

from datetime import UTC, datetime

from langgraph.types import interrupt

from app.config import get_settings
from orchestrator import audit
from orchestrator.agents.coding import rollback_last_applied
from orchestrator.state import OrchestratorState


def run(state: OrchestratorState) -> OrchestratorState:
    """Triggered after MAX_REPLANS is exhausted (see replan.py / graph.py's
    routers): halts the graph, rolls back any applied-but-unresolved code
    change, and surfaces the conflict to a human rather than looping
    indefinitely or failing silently.

    Rollback runs unconditionally (a system cleanup action, not something
    that needs human sign-off); the interrupt is a notification handoff,
    not an approval gate - there's nothing to approve, just something to
    know about. Under AUTO_APPROVE the notification pause is skipped so
    CI/scenario runs don't hang, but the halt and rollback still happen."""
    gate_log = state.get("gate_log", [])
    last_gate = gate_log[-1] if gate_log else None
    replan_count = state.get("replan_count", 0)

    reason = (
        f"safe-stop after {replan_count} re-plan(s): "
        f"{last_gate['gate_id']} ({last_gate['node']}) still failing: {last_gate['detail']}"
        if last_gate
        else f"safe-stop after {replan_count} re-plan(s): no gate_log entry found"
    )

    rollback_note = rollback_last_applied(state)
    audit.append_event(
        {
            "type": "safe_stop",
            "run_id": state.get("run_id"),
            "reason": reason,
            "rollback": rollback_note,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    settings = get_settings()
    if not settings.auto_approve:
        interrupt(
            {
                "type": "safe_stop",
                "reason": reason,
                "rollback": rollback_note,
            }
        )

    return {
        "safe_stopped": True,
        "safe_stop_reason": reason,
    }
