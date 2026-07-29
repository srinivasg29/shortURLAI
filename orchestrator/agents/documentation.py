from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from orchestrator.llm import call_llm, is_live
from orchestrator.state import DocDiff, OrchestratorState

SYSTEM_PROMPT = """You are the Documentation Agent in an agentic SDLC orchestrator for a URL \
shortener service. Given a requirement and a summary of the code change made to satisfy it, \
write a single changelog entry: 1-2 plain-prose sentences, no markdown headers, no code \
fences, no leading bullet or dash (the caller adds that)."""

_CHANGELOG_PATH = "docs/CHANGELOG.md"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _template_entry(normalized_spec: str, target_path: str) -> str:
    return f"Updated {target_path} to address: {normalized_spec}"


def _append_changelog(entry_text: str, run_id: str) -> str:
    full_path = _repo_root() / _CHANGELOG_PATH
    full_path.parent.mkdir(parents=True, exist_ok=True)
    before = full_path.read_text(encoding="utf-8") if full_path.exists() else "# Changelog\n\n"
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d")
    line = f"- [{timestamp}] ({run_id[:8]}) {entry_text}\n"
    full_path.write_text(before + line, encoding="utf-8")
    return line


def run(state: OrchestratorState) -> OrchestratorState:
    normalized_spec = state["normalized_spec"]
    run_id = state.get("run_id", "unknown")
    code_diffs = state.get("code_diffs", [])
    applied_diff = next((d for d in reversed(code_diffs) if d.get("applied")), None)

    if applied_diff is None:
        doc_diff: DocDiff = {
            "path": _CHANGELOG_PATH,
            "diff": "",
            "summary": f"Proposal only: no applied code change to document for: {normalized_spec}",
            "applied": False,
        }
        return {"doc_diffs": [doc_diff]}

    llm_mode = "mock"
    entry_text = _template_entry(normalized_spec, applied_diff["path"])

    if is_live():
        try:
            raw = call_llm(
                SYSTEM_PROMPT,
                f"Requirement: {normalized_spec}\n\nChange summary: {applied_diff['summary']}",
                node="documentation_agent",
            )
            candidate = raw.strip()
            if candidate:
                entry_text = candidate
                llm_mode = "live"
        except Exception:
            pass

    line = _append_changelog(entry_text, run_id)
    doc_diff = {
        "path": _CHANGELOG_PATH,
        "diff": line,
        "summary": f"Appended changelog entry for {applied_diff['path']}",
        "applied": True,
    }

    result: OrchestratorState = {"doc_diffs": [doc_diff]}
    if llm_mode == "mock":
        result["llm_mode"] = "mock"
    return result
