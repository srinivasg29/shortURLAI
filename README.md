# Agentic URL Shortener

A production-grade URL Shortener service, built alongside a LangGraph-based agentic SDLC
orchestrator that coordinates requirement understanding, planning, architecture, coding, testing,
review, and documentation for changes to this same codebase — with human approval gates, bounded
re-planning, and audit-grade traceability.

> Status: under active build-out. This README is filled in incrementally per phase; see
> [docs/workflow_gate_reference.md](docs/workflow_gate_reference.md) and
> [FINAL_ENGINEERING_SUMMARY.md](FINAL_ENGINEERING_SUMMARY.md) once those phases land.

## Project Overview

- `app/` — the FastAPI URL Shortener service (create, redirect, analytics).
- `orchestrator/` — the LangGraph agentic orchestration layer that plans and implements changes
  to `app/`, gated by automated checks and human approval.
- `scenarios/` — three end-to-end orchestrator runs (greenfield, brownfield, ambiguous) with
  committed transcripts under `scenarios/transcripts/`.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv\Scripts\Activate.ps1 in PowerShell
pip install -e ".[dev]"
cp .env.example .env
```

## Running the Service

```bash
uvicorn app.main:app --reload
```

- `POST /api/shorten` — create a short URL (`{"target_url": "https://..."}`).
- `GET /{code}` — 302 redirect to the target URL; records a click asynchronously.
- `GET /api/urls/{code}/stats` — click count and metadata for a short code.
- `GET /health` — liveness check.
- `GET /metrics` — Prometheus metrics.
- `GET /docs` — interactive OpenAPI docs (`/openapi.json` for the raw schema).

By default the service uses a local SQLite file (`data/shortener.db`) and an in-process TTL
cache for the redirect hot path. Set `REDIS_URL` in `.env` to use Redis instead.

## Testing

```bash
pytest                                   # unit + integration
pytest --cov=app --cov-report=term-missing
```

Tests run against a temporary SQLite file (never the dev `data/shortener.db`) with
Redis disabled, so no external services are required. `tests/unit/` covers the shortcode
generator, in-process cache, and the shortener service layer directly; `tests/integration/`
drives the full FastAPI app through `TestClient` for the create → redirect → stats flow and
the validation/expiration/error paths.

## Running the Agentic Orchestrator

The orchestrator is a [LangGraph](https://github.com/langchain-ai/langgraph) `StateGraph` over a
single typed `OrchestratorState` (`orchestrator/state.py`) threaded through every node; list-valued
fields (`gate_log`, `architecture_decisions`, etc.) use an `operator.add` reducer so nodes append
to the decision lineage instead of overwriting it. So far the graph runs three nodes in sequence:

- **Requirement Agent** (`orchestrator/agents/requirement.py`) — interprets a raw requirement,
  flags ambiguity, and normalizes it into an engineering-ready spec. Evaluates **Gate 0**
  (intake normalized, ambiguity flagged) automatically.
- **Planning Agent** (`orchestrator/agents/planning.py`) — decomposes the normalized spec into a
  `task_graph` of tasks with explicit `depends_on` edges, mirroring the orchestrator's own
  downstream phases (design → implement → test/document → review). Evaluates **Gate 1**
  (task graph + dependencies set) automatically, validating the graph is acyclic, has no
  duplicate task ids, and every `depends_on` reference resolves.
- **Architecture Agent** (`orchestrator/agents/architecture.py`) — proposes concrete architecture
  decisions (data model, API contract, storage implications) for the change. Evaluates **Gate 2**
  (`HUMAN APPROVAL: design`) — the first human checkpoint, since this is where the data model/API
  contract locks in and gets expensive to change later.

### Human approval gates (Gate 2, 5, 6)

These pause the graph rather than auto-passing. The mechanism is LangGraph's native
`interrupt()`/`Command(resume=...)`, backed by an in-memory checkpointer keyed on `run_id` — no
blocking `input()` calls inside library code, so the same graph runs identically whether it's
driven by a human at a terminal, a test, or a future API endpoint.

```python
from orchestrator.graph import start_run, resume_run

state = start_run("make the service more secure", scenario="ambiguous")
if "__interrupt__" in state:
    proposal = state["__interrupt__"][0].value
    # ... show proposal["proposals"] to a human, collect a decision ...
    state = resume_run(
        state["run_id"],
        {"approved": True, "approver": "human:sri", "comment": "looks good"},
    )
```

Setting `AUTO_APPROVE=1` (see `.env.example`) skips the interactive pause and auto-approves with
`approver="system:auto_approve"` — this is what CI and the scenario scripts (Phase 13) use, and
the audit trail records that it was an automatic, not human, approval.

Every gate decision is appended to both `state["gate_log"]` (in-memory decision lineage) and the
durable audit log at `AUDIT_LOG_PATH` (default `./audit_log.jsonl`, one JSON object per line);
resuming a paused gate also logs a `gate_resume` audit event with the raw decision payload.

When `ANTHROPIC_API_KEY` is unset, agents fall back to deterministic heuristics instead of calling
the model — `state["llm_mode"]` records which path ran (`"live"` or `"mock"`) for every run, so
mock-mode runs are visible in the audit trail rather than silently masquerading as real ones. A
node only ever downgrades this flag to `"mock"`, never upgrades it, so the flag reflects the
worst case across the whole run.
Coding, Testing, Documentation, Review, and Release Readiness agents land in later phases and
extend this same graph.
