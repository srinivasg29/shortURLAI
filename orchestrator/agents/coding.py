from __future__ import annotations

import ast
import difflib
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.codebase_map import identify_impacted_modules
from orchestrator.llm import call_llm, is_live
from orchestrator.state import ArchitectureDecision, CodeDiff, GateLogEntry, OrchestratorState

SYSTEM_PROMPT = """You are the Coding Agent in an agentic SDLC orchestrator for a URL \
shortener service. You will be given the normalized requirement, the approved architecture \
decisions, and the CURRENT full content of one source file. Output ONLY the complete new \
content of that file implementing the requirement - no explanations, no markdown fences, no \
diff syntax, just the raw file content that should replace it verbatim."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _pick_target_file(normalized_spec: str) -> str | None:
    candidates = identify_impacted_modules(normalized_spec)
    return candidates[0] if candidates else None


def _unified_diff(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
    stripped = re.sub(r"\n```$", "", stripped)
    return stripped


def _run_static_checks(path: str) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", path],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    passed = result.returncode == 0
    detail = "ruff check passed" if passed else (result.stdout.strip() or result.stderr.strip())
    return passed, detail


def _attempt_live_edit(
    path: str, normalized_spec: str, architecture_decisions: list[ArchitectureDecision]
) -> CodeDiff | None:
    full_path = _repo_root() / path
    if not full_path.exists():
        return None

    before = full_path.read_text(encoding="utf-8")
    decisions_text = "\n".join(
        f"- {d['decision']} ({d['rationale']})" for d in architecture_decisions
    )
    prompt = (
        f"Requirement: {normalized_spec}\n\n"
        f"Approved architecture decisions:\n{decisions_text}\n\n"
        f"Current content of {path}:\n{before}"
    )

    try:
        raw = call_llm(SYSTEM_PROMPT, prompt, max_tokens=4096, node="coding_agent")
    except Exception:
        return None

    after = _strip_markdown_fence(raw)

    try:
        ast.parse(after)
    except SyntaxError:
        return None

    if after == before:
        return None

    full_path.write_text(after, encoding="utf-8")
    return {
        "path": path,
        "diff": _unified_diff(path, before, after),
        "summary": f"Applied live-LLM edit to {path}",
        "applied": True,
        "before": before,
    }


def _proposal_only(path: str | None, normalized_spec: str) -> CodeDiff:
    if path:
        summary = (
            f"Proposal only (no live LLM available): identify_impacted_modules() suggests "
            f"{path} as the primary file to change for: {normalized_spec}"
        )
    else:
        path = "UNSPECIFIED"
        summary = (
            "Proposal only (no live LLM available, and no impacted module could be "
            f"identified) for: {normalized_spec}"
        )
    return {"path": path, "diff": "", "summary": summary, "applied": False, "before": ""}


def rollback_last_applied(state: OrchestratorState) -> str | None:
    """Reverts the most recently applied code change back to its
    pre-change content - the plan's Rollback control. Returns a human
    -readable description of what happened, or None if there was nothing
    to revert (mock mode never applies anything, so this is a no-op in
    every automated test run)."""
    code_diffs = state.get("code_diffs", [])
    applied = next((d for d in reversed(code_diffs) if d.get("applied")), None)
    if applied is None:
        return None

    full_path = _repo_root() / applied["path"]
    full_path.write_text(applied["before"], encoding="utf-8")
    return f"reverted {applied['path']} to its pre-change content"


def run(state: OrchestratorState) -> OrchestratorState:
    normalized_spec = state["normalized_spec"]
    architecture_decisions: list[Any] = state.get("architecture_decisions", [])
    target_path = _pick_target_file(normalized_spec)

    code_diff: CodeDiff | None = None
    llm_mode = "mock"

    if is_live() and target_path:
        code_diff = _attempt_live_edit(target_path, normalized_spec, architecture_decisions)
        if code_diff is not None:
            llm_mode = "live"

    if code_diff is None:
        code_diff = _proposal_only(target_path, normalized_spec)

    if code_diff["applied"]:
        passed, detail = _run_static_checks(code_diff["path"])
    else:
        passed, detail = True, "no changes applied; nothing to statically check"

    gate_entry: GateLogEntry = {
        "gate_id": "gate_3",
        "node": "coding_agent",
        "passed": passed,
        "approver": "system",
        "entry_criteria": "architecture_decisions approved at Gate 2",
        "exit_criteria": "build + static checks pass",
        "timestamp": datetime.now(UTC).isoformat(),
        "detail": detail,
    }

    result: OrchestratorState = {
        "code_diffs": [code_diff],
        "gate_log": [gate_entry],
    }
    if llm_mode == "mock":
        result["llm_mode"] = "mock"
    return result
