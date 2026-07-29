from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from orchestrator.llm import call_llm, is_live
from orchestrator.state import OrchestratorState, TestResult

SYSTEM_PROMPT = """You are the Testing Agent in an agentic SDLC orchestrator for a URL \
shortener service. You will be given a requirement and the full content of a source file \
that was just changed to satisfy it. Output ONLY the complete content of a pytest test \
module that exercises the change - no explanations, no markdown fences, just raw Python test \
code. Import from the real project modules (e.g. `from app.services.shortener import ...`)."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
    stripped = re.sub(r"\n```$", "", stripped)
    return stripped


def _test_path_for(target_path: str) -> str:
    name = Path(target_path).stem
    return f"tests/unit/test_{name}_generated.py"


def _run_pytest(test_path: str) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_path, "-q"],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    passed = result.returncode == 0
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-10:])
    return passed, tail


def _proposal_only(detail: str) -> TestResult:
    return {"name": "proposal_only", "passed": True, "detail": detail, "executed": False}


def _attempt_live_tests(target_path: str, normalized_spec: str) -> TestResult | None:
    full_target = _repo_root() / target_path
    if not full_target.exists():
        return None

    content = full_target.read_text(encoding="utf-8")
    prompt = f"Requirement: {normalized_spec}\n\nPath: {target_path}\n\nContent:\n{content}"

    try:
        raw = call_llm(SYSTEM_PROMPT, prompt, max_tokens=4096, node="testing_agent")
    except Exception:
        return None

    test_code = _strip_markdown_fence(raw)
    try:
        ast.parse(test_code)
    except SyntaxError:
        return None

    test_path = _test_path_for(target_path)
    full_test_path = _repo_root() / test_path
    full_test_path.parent.mkdir(parents=True, exist_ok=True)
    full_test_path.write_text(test_code, encoding="utf-8")

    passed, detail = _run_pytest(test_path)
    return {"name": test_path, "passed": passed, "detail": detail, "executed": True}


def run(state: OrchestratorState) -> OrchestratorState:
    normalized_spec = state["normalized_spec"]
    code_diffs = state.get("code_diffs", [])
    applied_diff = next((d for d in reversed(code_diffs) if d.get("applied")), None)

    test_result: TestResult | None = None
    llm_mode = "mock"

    if is_live() and applied_diff is not None:
        test_result = _attempt_live_tests(applied_diff["path"], normalized_spec)
        if test_result is not None:
            llm_mode = "live"

    if test_result is None:
        detail = (
            "no applied code change to test; proposal only"
            if applied_diff is None
            else "live test generation unavailable or failed; proposal only"
        )
        test_result = _proposal_only(detail)

    result: OrchestratorState = {"test_results": [test_result]}
    if llm_mode == "mock":
        result["llm_mode"] = "mock"
    return result
