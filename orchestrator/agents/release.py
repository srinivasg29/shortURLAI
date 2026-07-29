from __future__ import annotations

from datetime import UTC, datetime

from langgraph.types import interrupt

from app.config import get_settings
from orchestrator.state import GateLogEntry, OrchestratorState


def _readiness_checklist(state: OrchestratorState) -> tuple[bool, str]:
    gate_log = state.get("gate_log", [])
    failed = [g["gate_id"] for g in gate_log if not g["passed"]]
    ready = not failed
    detail = "all prior gates passed" if ready else f"prior gate failures: {failed}"
    return ready, detail


def run(state: OrchestratorState) -> OrchestratorState:
    ready, checklist_detail = _readiness_checklist(state)
    settings = get_settings()
    now = datetime.now(UTC).isoformat()

    if settings.auto_approve:
        # Same principle as Review's auto-approve: skip the interactive
        # pause, but never rubber-stamp a release whose own checklist
        # failed.
        approved = ready
        approver = "system:auto_approve"
        detail = f"AUTO_APPROVE=1: {checklist_detail}"
    else:
        response = interrupt(
            {
                "gate_id": "gate_6",
                "prompt": "Approve release?",
                "checklist": checklist_detail,
                "ready": ready,
            }
        )
        if isinstance(response, dict):
            approved = bool(response.get("approved", False))
            approver = response.get("approver") or "human"
            detail = response.get("comment") or checklist_detail
        else:
            approved = bool(response)
            approver = "human"
            detail = checklist_detail

    gate_entry: GateLogEntry = {
        "gate_id": "gate_6",
        "node": "release_readiness_agent",
        "passed": approved,
        "approver": approver,
        "entry_criteria": "Gate 5 quality sign-off complete",
        "exit_criteria": "HUMAN APPROVAL: release",
        "timestamp": now,
        "detail": detail,
    }

    result: OrchestratorState = {"gate_log": [gate_entry], "released": approved}
    return result
