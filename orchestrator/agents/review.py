from __future__ import annotations

from datetime import UTC, datetime

from langgraph.types import interrupt

from app.config import get_settings
from orchestrator.llm import call_llm, is_live
from orchestrator.state import GateLogEntry, OrchestratorState

SYSTEM_PROMPT = """You are the Review Agent in an agentic SDLC orchestrator for a URL \
shortener service. Given a summary of the run so far (requirement, architecture decisions, \
code change, test result, documentation), write a 2-4 sentence quality assessment: does the \
work meet the bar for release? Call out any concerns plainly. Output ONLY the assessment text \
- no markdown, no headers."""


def _run_facts(state: OrchestratorState) -> str:
    code_diffs = state.get("code_diffs", [])
    test_results = state.get("test_results", [])
    doc_diffs = state.get("doc_diffs", [])
    gate_log = state.get("gate_log", [])

    applied = any(d.get("applied") for d in code_diffs)
    tests_passed = bool(test_results) and test_results[-1]["passed"]
    docs_complete = bool(doc_diffs)
    gates_failed = [g["gate_id"] for g in gate_log if not g["passed"]]

    return (
        f"code_applied={applied}, tests_passed={tests_passed}, docs_complete={docs_complete}, "
        f"gates_failed={gates_failed or 'none'}"
    )


def _quality_gates_passed(state: OrchestratorState) -> bool:
    relevant = {
        g["gate_id"]: g["passed"]
        for g in state.get("gate_log", [])
        if g["gate_id"] in ("gate_3", "gate_4")
    }
    return bool(relevant) and all(relevant.values())


def _quality_summary(state: OrchestratorState) -> tuple[str, str]:
    facts = _run_facts(state)
    if is_live():
        try:
            prompt = f"Requirement: {state.get('normalized_spec', '')}\n\nRun facts: {facts}"
            text = call_llm(SYSTEM_PROMPT, prompt, node="review_agent").strip()
            if text:
                return text, "live"
        except Exception:
            pass
    return f"Automated summary (no live LLM): {facts}", "mock"


def run(state: OrchestratorState) -> OrchestratorState:
    summary_text, llm_mode = _quality_summary(state)
    settings = get_settings()
    now = datetime.now(UTC).isoformat()

    if settings.auto_approve:
        # Auto-approve is conditional, not a rubber stamp: CI/scenario runs
        # only sail through Gate 5 if the quality gates it's meant to
        # confirm (Gate 3 build/static checks, Gate 4 tests+docs) actually
        # passed. Otherwise it fails closed, same as a careful reviewer
        # would.
        approved = _quality_gates_passed(state)
        approver = "system:auto_approve"
        detail = f"AUTO_APPROVE=1 ({'gates 3&4 passed' if approved else 'gates 3&4 not both passed'}): {summary_text}"
    else:
        response = interrupt(
            {
                "gate_id": "gate_5",
                "prompt": "Approve this quality sign-off?",
                "summary": summary_text,
            }
        )
        if isinstance(response, dict):
            approved = bool(response.get("approved", False))
            approver = response.get("approver") or "human"
            detail = response.get("comment") or summary_text
        else:
            approved = bool(response)
            approver = "human"
            detail = summary_text

    gate_entry: GateLogEntry = {
        "gate_id": "gate_5",
        "node": "review_agent",
        "passed": approved,
        "approver": approver,
        "entry_criteria": "code, tests, and docs available from Gate 3/4",
        "exit_criteria": "HUMAN APPROVAL: quality sign-off",
        "timestamp": now,
        "detail": detail,
    }

    result: OrchestratorState = {"gate_log": [gate_entry]}
    if llm_mode == "mock":
        result["llm_mode"] = "mock"
    return result
