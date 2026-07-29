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
- `GET /metrics` — Prometheus metrics for the HTTP service itself.
- `GET /orchestrator/metrics` — Prometheus metrics for the orchestrator (success rate, retry/
  rollback frequency, MTTR, latency breakdown — see [Observability](#observability)).
- `GET /orchestrator/runs/{run_id}` — one run's full audit timeline as JSON.
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
to the decision lineage instead of overwriting it. So far the graph runs:

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
- **Coding Agent** (`orchestrator/agents/coding.py`) — picks a target source file via
  `orchestrator/codebase_map.py` (a keyword → file heuristic that doubles as the brownfield
  "Codebase Reasoning" capability), then either applies a real edit or produces an unapplied
  proposal. Evaluates **Gate 3** (build + static checks pass) automatically.

  This is the one agent that can touch the real filesystem, so it's deliberately conservative:
  - **Live** (`ANTHROPIC_API_KEY` set): sends the current file content + requirement + approved
    architecture decisions to the model, which returns the complete new file content. The result
    is only written to disk if it parses as valid Python (`ast.parse`) and actually differs from
    the original; otherwise it falls back to the mock path below. After writing, Gate 3 runs a
    real `ruff check` against the file and fails the gate (without reverting — rollback lands in
    Phase 11) if it doesn't pass.
  - **Mock** (no API key, or the live attempt didn't produce an applicable change): produces a
    `code_diffs` entry with `applied: False` and an empty diff — a labeled proposal, not a
    filesystem change. **The repository is never mutated in mock mode**, which is what every
    automated test in this repo runs under.

### The first parallel branch: Testing + Documentation, synced at Gate 4

Coding fans out to two nodes that run off the same output — this is the graph's first genuine
parallel branch, not just a longer sequential chain:

```
coding --> testing ------\
       \-> documentation -+--> gate4_sync --> ...
```

- **Testing Agent** (`orchestrator/agents/testing.py`) — if Coding actually applied a change,
  live mode asks the model for a pytest module exercising it, validates the module parses, writes
  it to `tests/unit/test_<module>_generated.py`, and **actually runs it** with a real `pytest`
  subprocess — a genuine pass/fail signal, not a simulated one. If Coding produced only a
  proposal (mock mode, or no target identified), Testing has nothing concrete to exercise and
  records a `proposal_only` result that trivially passes (`executed: False`), the same "nothing
  to check" convention Gate 3 uses.
- **Documentation Agent** (`orchestrator/agents/documentation.py`) — same conservatism: only
  appends a changelog entry to `docs/CHANGELOG.md` when a code change was actually applied. Live
  mode asks the model for the entry text; mock mode (or a failed live call) falls back to a fixed
  template — the plan's own example of the Fallback control ("template-based doc generation if
  the Documentation Agent fails").
- **`gate4_sync`** (`orchestrator/agents/sync.py`) — runs once *both* branches have completed
  (LangGraph only executes a node once every incoming edge has fired, which is what makes this a
  real synchronization point rather than two independent checks under a shared name), and
  evaluates **Gate 4** (`tests pass AND docs complete`) by reading both `state["test_results"]`
  and `state["doc_diffs"]` — proof, via a single gate_log entry, that both parallel branches
  actually wrote into the same shared state rather than one clobbering the other.

### Review and Release Readiness: Gate 5 and Gate 6

```
gate4_sync --> review --> release --> END
```

- **Review Agent** (`orchestrator/agents/review.py`) — synthesizes a quality summary from the
  run so far (was code applied, did tests pass, are docs complete, which gates failed) and gates
  on it at **Gate 5** (`HUMAN APPROVAL: quality sign-off`).
- **Release Readiness Agent** (`orchestrator/agents/release.py`) — runs an automated readiness
  checklist (every prior gate in `gate_log` passed?) and gates on it at **Gate 6**
  (`HUMAN APPROVAL: release`), the final production-impacting action. On approval,
  `state["released"]` is set.

Both agents' `AUTO_APPROVE=1` path is deliberately conditional, not a rubber stamp: Gate 5
auto-approves only if Gates 3 and 4 both passed; Gate 6 auto-approves only if *every* gate
in the log passed. A CI run with a failing test doesn't sail through these gates just because
no human was watching — it fails closed, the same way a careful reviewer would. A human resuming
an interactive run can still override and approve anyway (their call, not the system's to make
silently) — see `test_release_readiness_blocks_when_reviewer_rejects` for that path.

### Human approval gates (Gate 2, 5, 6)

These pause the graph rather than auto-passing. The mechanism is LangGraph's native
`interrupt()`/`Command(resume=...)`, backed by an in-memory checkpointer keyed on `run_id` — no
blocking `input()` calls inside library code, so the same graph runs identically whether it's
driven by a human at a terminal, a test, or a future API endpoint. A single run can pause and
resume through all three gates in sequence — each `resume_run` call picks up wherever the graph
is currently paused, not just the first gate it ever hit:

```python
from orchestrator.graph import start_run, resume_run

state = start_run("make the service more secure", scenario="ambiguous")
while "__interrupt__" in state:
    gate = state["__interrupt__"][0].value
    # ... show gate to a human, collect a decision ...
    state = resume_run(
        state["run_id"],
        {"approved": True, "approver": "human:sri", "comment": "looks good"},
    )
```

Setting `AUTO_APPROVE=1` (see `.env.example`) skips the interactive pause at all three gates —
this is what CI and the scenario scripts (Phase 13) use — and the audit trail records that it
was an automatic, not human, approval at each one.

Every gate decision is appended to both `state["gate_log"]` (in-memory decision lineage) and the
durable audit log at `AUDIT_LOG_PATH` (default `./audit_log.jsonl`, one JSON object per line);
resuming a paused gate also logs a `gate_resume` audit event with the raw decision payload.

When `ANTHROPIC_API_KEY` is unset, agents fall back to deterministic heuristics instead of calling
the model — `state["llm_mode"]` records which path ran (`"live"` or `"mock"`) for every run, so
mock-mode runs are visible in the audit trail rather than silently masquerading as real ones. A
node only ever downgrades this flag to `"mock"`, never upgrades it, so the flag reflects the
worst case across the whole run.

This is the full seven-gate graph (`requirement → planning → architecture → coding →
{testing, documentation} → gate4_sync → review → release`).

### Re-planning, retry, fallback, rollback, safe-stop

Three checkpoints — Gate 2 (Architecture), Gate 3 (Coding), and Gate 4 (`gate4_sync`, standing in
for Testing since re-routing away from a fan-in node isn't safe — see below) — are wired as
**conditional edges**, not plain ones:

```
                 pass
architecture ----------> coding
     |  fail                |  fail
     v                      v
 (replan / safe-stop)  (replan / safe-stop)

coding --pass--> [testing, documentation] --> gate4_sync --pass--> review
                                                    |  fail
                                                    v
                                          (replan / safe-stop)
```

- **Re-plan**: on failure, if `replan_count < MAX_REPLANS` (2), routes to `replan_node`
  (`orchestrator/agents/replan.py`), which reads the failing gate's detail off `gate_log[-1]`,
  appends a `replan_log` entry, and loops back to **Planning** — not a retry of the same node,
  a change to the task graph itself. `planning.py` reads that reason back out
  (`replan_log[-1]["trigger_reason"]`) and inserts a `remediate` task naming the specific
  failure, so a re-plan is a genuine plan change rather than re-deriving the same task_graph
  from an unchanged `normalized_spec`.
- **Safe-stop**: once `replan_count` hits `MAX_REPLANS`, routes to `safe_stop_node`
  (`orchestrator/agents/safe_stop.py`) instead of a third re-plan. It rolls back any applied-
  but-unresolved code change (see Rollback below), sets `state["safe_stopped"]` /
  `state["safe_stop_reason"]`, and — unless `AUTO_APPROVE` is set — pauses with an `interrupt()`
  notification (`{"type": "safe_stop", "reason": ..., "rollback": ...}`) so a human can inspect
  what happened. It's a notification handoff, not an approval gate: there's nothing to approve,
  and any resume value just lets the run finish. Under `AUTO_APPROVE`, the notification is
  skipped but the halt and rollback still happen, so CI doesn't hang.
- **Retry**: `orchestrator/llm.py`'s `call_llm` retries the same call up to `MAX_RETRIES` (2)
  times on any failure before raising — distinct from re-plan (same node, same inputs, not a
  task-graph change) and logged per attempt as an `llm_retry` audit event. Only once retries are
  exhausted does an agent's existing except-block **Fallback** (the deterministic heuristic every
  agent has had since Phase 5) take over.
- **Rollback**: `coding.rollback_last_applied()` finds the most recent `code_diffs` entry with
  `applied: True` and writes its `before` content back to disk, undoing an unresolved change
  rather than leaving a broken edit sitting in the working tree. Runs automatically inside
  `safe_stop_node` — a system cleanup action, not something that waits on human sign-off.

A conditional router can only return a single node, but `coding`'s "pass" outcome needs to reach
*two* nodes (`testing` and `documentation`) — LangGraph supports this by letting a router return
a list of target names instead of one, which is how the fan-out and the re-plan/safe-stop routing
share the same conditional edge. This was verified with a throwaway script (bounded loop reaching
safe-stop after exactly `MAX_REPLANS` iterations) before wiring the real agents — see
`test_persistent_gate4_failure_replans_then_safe_stops` and
`test_repeated_gate_2_rejection_reaches_safe_stop_after_max_replans` for the equivalent behavior
through the real graph.

Testing (not Coding) is the literal trigger named in the plan for the third checkpoint, but
Testing is a parallel branch feeding into `gate4_sync`'s fan-in — conditionally routing *away*
from a fan-in predecessor risks gate4_sync waiting on an edge that never fires. Checking Gate 4
after the sync point achieves the same effect safely: in this design, `gate4_sync` can only fail
because Testing failed (Documentation always trivially "completes"), so it's a faithful stand-in.

## Observability

- **Audit log** (`orchestrator/audit.py`) — every gate decision, code/test/doc diff, re-plan,
  safe-stop, and LLM call/retry is appended as one JSON line to `AUDIT_LOG_PATH`
  (`./audit_log.jsonl` by default), each auto-stamped with a timestamp if the caller didn't
  already set one. This is the single source of truth everything else in this section reads from
  — nothing here is tracked separately in-process, so it can't drift from what actually happened.
- **Prometheus** — `GET /metrics` (HTTP-level service metrics) and `GET /orchestrator/metrics`
  (Section 8's reliability metrics: success rate, retry/rollback frequency by node, MTTR,
  end-to-end latency split into automated vs. human-approval wait time — computed fresh from the
  audit log by `orchestrator/metrics.py` on every scrape).
- **Grafana** — `observability/grafana-dashboard.json` is a real, importable dashboard covering
  every metric above; `observability/prometheus.yml` is a matching scrape config. See
  [`observability/README.md`](observability/README.md) for how to wire them up locally.
- **Tracing** — `app/tracing.py` configures OpenTelemetry with a `ConsoleSpanExporter`; every
  orchestrator node execution and every FastAPI request emits a span, with each run's nodes
  nesting under one parent `run`/`run_resume` span (`run_id`, and `gate_id`/`gate_passed` when
  applicable, as attributes) — a full trace tree per run, inspectable from stdout with no
  external collector needed for local development.
- **Run timeline** — `GET /orchestrator/runs/{run_id}` reconstructs one run's full decision
  lineage from the audit log as JSON, independent of whether that run's in-memory
  `OrchestratorState` still exists.
