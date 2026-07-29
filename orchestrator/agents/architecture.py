from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from app.config import get_settings
from orchestrator.llm import call_llm, is_live
from orchestrator.state import ArchitectureDecision, GateLogEntry, OrchestratorState

SYSTEM_PROMPT = """You are the Architecture Agent in an agentic SDLC orchestrator for a URL \
shortener service. Given a normalized engineering spec, propose the architecture decisions \
needed to implement it: data model changes, API contract changes, and any storage or \
consistency implications.

Respond with ONLY a JSON object (no prose, no markdown fences):
{
  "decisions": [
    {"decision": "<a specific, concrete decision>", "rationale": "<why, and the alternative rejected>"}
  ]
}
Use 2-4 decisions."""


def _extract_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(match.group(0) if match else raw)


def default_proposals(normalized_spec: str) -> list[dict[str, str]]:
    """Deterministic fallback proposal used when no LLM is configured, or the
    live call fails. Deliberately generic — a real architecture proposal
    needs the LLM; this exists so the gate still has something concrete to
    approve/reject rather than blocking the graph outright."""
    return [
        {
            "decision": f"Extend the existing ShortUrl schema/API surface to support: {normalized_spec}",
            "rationale": (
                "Reuses the current SQLAlchemy model and FastAPI routers instead of "
                "introducing a parallel data path, keeping the change reviewable as a "
                "single diff."
            ),
        },
        {
            "decision": "No new external dependency or service is introduced for this change.",
            "rationale": (
                "The existing SQLite/Postgres + optional Redis cache stack already covers "
                "the access patterns implied by this spec; adding infrastructure without a "
                "demonstrated need would be premature."
            ),
        },
    ]


def _propose(normalized_spec: str) -> tuple[list[dict[str, str]], str]:
    if is_live():
        try:
            raw = call_llm(SYSTEM_PROMPT, normalized_spec, node="architecture_agent")
            parsed = _extract_json(raw)
            decisions = parsed.get("decisions")
            if decisions:
                return decisions, "live"
        except Exception:
            pass
    return default_proposals(normalized_spec), "mock"


def run(state: OrchestratorState) -> OrchestratorState:
    normalized_spec = state["normalized_spec"]
    proposals, llm_mode = _propose(normalized_spec)
    now = datetime.now(UTC).isoformat()
    settings = get_settings()

    if settings.auto_approve:
        approved = True
        approver = "system:auto_approve"
        detail = "AUTO_APPROVE=1: Gate 2 approved without an interactive checkpoint"
    else:
        response = interrupt(
            {
                "gate_id": "gate_2",
                "prompt": "Approve this architecture design?",
                "proposals": proposals,
            }
        )
        if isinstance(response, dict):
            approved = bool(response.get("approved", False))
            approver = response.get("approver") or "human"
            detail = response.get("comment", "")
        else:
            approved = bool(response)
            approver = "human"
            detail = ""

    decisions: list[ArchitectureDecision] = [
        {
            "decision": p["decision"],
            "rationale": p["rationale"],
            "approved_by": approver if approved else f"rejected_by:{approver}",
            "timestamp": now,
        }
        for p in proposals
    ]

    gate_entry: GateLogEntry = {
        "gate_id": "gate_2",
        "node": "architecture_agent",
        "passed": approved,
        "approver": approver,
        "entry_criteria": "normalized_spec and task_graph available",
        "exit_criteria": "HUMAN APPROVAL: design",
        "timestamp": now,
        "detail": detail or f"{len(proposals)} decision(s) {'approved' if approved else 'rejected'}",
    }

    result: OrchestratorState = {
        "architecture_decisions": decisions,
        "gate_log": [gate_entry],
    }
    if llm_mode == "mock":
        result["llm_mode"] = "mock"
    return result
