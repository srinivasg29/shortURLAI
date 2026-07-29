from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from orchestrator.llm import call_llm, is_live
from orchestrator.state import GateLogEntry, OrchestratorState

SYSTEM_PROMPT = """You are the Requirement Agent in an agentic SDLC orchestrator for a URL \
shortener service. Given a raw stakeholder requirement, interpret intent, identify \
ambiguity, and normalize it into a clear engineering problem.

Respond with ONLY a JSON object (no prose, no markdown fences):
{
  "requirement_summary": "<one paragraph restating what was asked>",
  "identified_ambiguities": ["<concrete interpretation 1>", "<concrete interpretation 2>", ...],
  "normalized_spec": "<a precise, engineering-ready restatement scoped to one interpretation>"
}
If the requirement is well-defined, "identified_ambiguities" must be an empty list. If it is \
ambiguous, list 2-3 concrete, mutually distinct interpretations and pick the most defensible \
one for "normalized_spec", stating that a human should confirm the choice at the next gate."""

# Trigger phrases from this project's own "ambiguous" scenario definition
# (Section 4 of the plan): a stakeholder asking to "make the service more
# secure" with no further detail.
_VAGUE_SECURITY_MARKERS = ("more secure", "improve security", "harden", "make it secure")


def _extract_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(match.group(0) if match else raw)


def _heuristic_requirement_analysis(raw_requirement: str) -> dict[str, Any]:
    """Deterministic fallback used when no LLM is configured, or the LLM
    call/response fails. Recognizes this project's own ambiguous-security
    scenario explicitly; anything else passes through with no ambiguity
    flagged (better to under-flag than to fabricate ambiguity)."""
    text = raw_requirement.strip()
    lowered = text.lower()

    if any(marker in lowered for marker in _VAGUE_SECURITY_MARKERS):
        return {
            "requirement_summary": f"Stakeholder request: {text}",
            "identified_ambiguities": [
                "Rate limiting on create/redirect endpoints to blunt abuse and enumeration",
                "Higher-entropy short codes to make guessing/scanning codes impractical",
                "Redirect target allowlisting/denylisting to block malicious destinations",
            ],
            "normalized_spec": (
                "Requirement is underspecified. Pending human confirmation at Gate 0/1, "
                "defaulting to rate limiting on POST /api/shorten and GET /{code} as the "
                "concrete scope, since it addresses the most common abuse vector "
                "(automated link creation / scanning) with the least behavior change."
            ),
        }

    return {
        "requirement_summary": text,
        "identified_ambiguities": [],
        "normalized_spec": text,
    }


def _analyze(raw_requirement: str) -> tuple[dict[str, Any], str]:
    if is_live():
        try:
            raw = call_llm(SYSTEM_PROMPT, raw_requirement)
            return _extract_json(raw), "live"
        except Exception:
            pass
    return _heuristic_requirement_analysis(raw_requirement), "mock"


def run(state: OrchestratorState) -> OrchestratorState:
    raw_requirement = state["raw_requirement"]
    parsed, llm_mode = _analyze(raw_requirement)

    gate_passed = bool(parsed.get("normalized_spec"))
    gate_entry: GateLogEntry = {
        "gate_id": "gate_0",
        "node": "requirement_agent",
        "passed": gate_passed,
        "approver": "system",
        "entry_criteria": "raw_requirement provided",
        "exit_criteria": "intake normalized, ambiguity flagged",
        "timestamp": datetime.now(UTC).isoformat(),
        "detail": f"{len(parsed['identified_ambiguities'])} ambiguity option(s) flagged",
    }

    return {
        "requirement_summary": parsed["requirement_summary"],
        "identified_ambiguities": parsed["identified_ambiguities"],
        "normalized_spec": parsed["normalized_spec"],
        "llm_mode": llm_mode,
        "gate_log": [gate_entry],
    }
