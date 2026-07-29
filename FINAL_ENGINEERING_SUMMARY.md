# Final Engineering Summary

Agentic URL Shortener — a production-grade URL shortener plus a LangGraph-based agentic SDLC
orchestrator that plans, implements, tests, documents, reviews, and releases changes to that
same codebase, with human approval gates, bounded re-planning, and audit-grade traceability.

This is a standalone deliverable, separate from [`README.md`](README.md): the README is "how to
run and use this"; this document is "why it's built this way, what was validated, what's
assumed, and what's left."

## 1. Plan and Rationale

### 1.1 Technology choice

The original plan considered a Java/Spring Boot + Python/LangGraph hybrid. That was dropped in
favor of a single Python stack (FastAPI + LangGraph + SQLAlchemy) before any code was written.
Rationale, unchanged from the initial planning pass: the assignment weights the orchestration
layer as the "critical differentiator," not the backend language. A second framework on the
critical path (Spring Boot, learned from scratch) would have spent time on plumbing instead of
on the dependency graph, parallel synchronization, re-planning, and audit trail that are
actually being evaluated. If a Java/Spring Boot expectation exists outside the assessment
document as provided, that's the one assumption in this plan that would need revisiting first.

### 1.2 Orchestration design

`orchestrator/graph.py` is a single LangGraph `StateGraph` over one typed `OrchestratorState`
(`orchestrator/state.py`), built up phase by phase (Phases 5–11) rather than designed monolithically
up front:

- **Phase 5–6**: state schema (append-only list fields via `operator.add` reducers) +
  Requirement + Planning agents — automated Gates 0–1.
- **Phase 7**: Architecture agent + the first human checkpoint (Gate 2), via LangGraph's native
  `interrupt()`/`Command(resume=...)` rather than a blocking `input()` call — chosen specifically
  so the same graph behaves identically under a human, a test, or a future API endpoint.
- **Phase 8**: Coding agent — the one agent that touches the real filesystem, deliberately
  conservative (see §3.1).
- **Phase 9**: the first genuine parallel branch (Testing + Documentation fanning out from
  Coding, synchronized at `gate4_sync`) — verified with a throwaway LangGraph script before
  wiring real agents, to confirm the fan-out/fan-in/reducer-merge mechanics actually work the
  way the plan assumes they do.
- **Phase 10**: Review + Release Readiness agents, completing the seven-gate graph.
- **Phase 11**: conditional edges at Gates 2/3/4 for bounded re-planning, a `MAX_RETRIES` retry
  loop in the LLM wrapper, rollback of unresolved applied changes, and safe-stop once re-plan
  budget is exhausted.
- **Phase 12**: observability — every metric computed from the audit log rather than tracked
  separately in-process, so it can't drift from what actually happened.
- **Phase 13**: three real scenarios run through the graph, each pairing a governance transcript
  with an actual shipped code change.

Full detail (why `gate4_sync` stands in for "Testing" as a re-plan trigger, why a LangGraph
router can return a list of targets, why the checkpointer must be a cached singleton) is in
[`README.md`](README.md) and [`docs/workflow_gate_reference.md`](docs/workflow_gate_reference.md)
rather than duplicated here.

## 2. Artifact List

| Artifact | Location |
|---|---|
| URL shortener service (FastAPI, SQLAlchemy) | `app/` |
| Orchestrator (LangGraph agents, state, graph) | `orchestrator/` |
| Prometheus/Grafana/tracing wiring | `app/tracing.py`, `app/routers/observability.py`, `observability/` |
| API schema | auto-generated OpenAPI at `/openapi.json`; see `app/schemas.py` |
| Tests (165, 99% combined coverage) | `tests/unit/`, `tests/integration/` |
| Three scenario write-ups + real audit-log transcripts | `scenarios/` |
| Architecture / gate reference docs | `README.md`, `docs/workflow_gate_reference.md` |
| Durable audit log (generated at runtime) | `AUDIT_LOG_PATH`, default `./audit_log.jsonl` |
| CI | `.github/workflows/ci.yml` |
| This document | `FINAL_ENGINEERING_SUMMARY.md` |

Commit history: 14 phases (2 → 13), each as its own branch → PR → merge into `main`, plus the
Phase 1 scaffold — 29 commits on `main`, one PR per phase.

## 3. Risks, Trade-offs, and Validation

### 3.1 The Coding Agent can write real files — deliberately constrained

Risk: an agent that edits the working tree is the one place a bug (or a bad LLM response) can
do real damage — including to the automated test suite running against this same repository.

Mitigation, validated by construction rather than by hope: in mock mode (no `ANTHROPIC_API_KEY`
— true for every automated test in this repo and for this sandboxed development environment),
the Coding/Testing/Documentation agents **never touch disk** — they produce a labeled,
`applied: false` proposal instead. In live mode, a write only happens after the response parses
as valid Python (`ast.parse`) and actually differs from the current content; Gate 3 then runs a
real `ruff check` and fails closed if it doesn't pass. `git status --short` was checked after
every test run throughout development specifically to catch any unintended repository mutation
— none occurred.

Trade-off accepted: this means a from-scratch `pytest` run in this environment never exercises
the *live* code-writing path end-to-end (only the mock path, plus unit tests that monkeypatch
the live path's internals directly). Confirmed correct by code review and by unit tests that
simulate a live LLM response, but not by an actual live `ANTHROPIC_API_KEY` run in this session.

### 3.2 Single-file-per-run limitation

The Coding Agent targets exactly one file per run (via `codebase_map.py`'s keyword heuristic).
All three Phase 13 scenarios' real implementations touch more than one file (e.g. the vanity-alias
feature spans `schemas.py`, `services/shortener.py`, and `routers/shorten.py`). The orchestrator
transcripts for those scenarios correctly identify the *primary* file; the scenario docs
(`scenarios/*.md`) say so explicitly rather than presenting the transcript as the full story.
Multi-file changes in a single Coding Agent turn are the natural next capability — not built
here because it meaningfully increases the blast radius of an unreviewed live edit, which cuts
against §3.1's mitigation.

### 3.3 Brownfield concurrency bug — reproduced empirically, not just reasoned about

The original `record_click()` (Phase 2) was a textbook read-modify-write race: each background
click-recording task opens its own DB session, so concurrent redirects for the same code could
both read the same `click_count` and both write back the same increment, silently losing one.
Before writing the fix (Phase 13, brownfield scenario), this was **reproduced**, not just
argued: a 20-threads × 10-clicks-each workload against the original implementation recorded 14
of 200 clicks — a ~93% loss rate. The fix (an atomic `UPDATE ... SET click_count = click_count +
1`) was validated against the identical workload, with the regression test now permanently
guarding it (`test_record_click_has_no_lost_updates_under_concurrent_redirects`).

### 3.4 Fan-in vs. conditional re-plan routing

Section 3.2 of the original plan names Architecture, Coding, *and Testing* as re-plan triggers.
Testing is a parallel branch feeding `gate4_sync`'s fan-in; LangGraph only runs a fan-in node
once every incoming edge has fired, so a conditional edge routing *away* from Testing (back to
Planning) risks `gate4_sync` waiting on an edge that never arrives. Verified this constraint with
a throwaway LangGraph script (see `README.md`'s Re-planning section) before deciding: check Gate
4 (which can only fail because Testing failed, since Documentation always trivially "completes"
in this design) as the third checkpoint instead of Testing directly. Same effect, no fan-in
deadlock risk.

### 3.5 Rate limiter and cache are in-process, not distributed

Both `app/cache.py` (Phase 2) and `app/rate_limit.py` (Phase 13) are in-process, single-instance
data structures by design, mirroring each other's shape. Both say so directly in their own
docstrings rather than presenting single-instance behavior as if it were distributed. A
multi-instance deployment needs a Redis-backed version of each; `REDIS_URL` is already wired for
the cache (falls back automatically when unset) but the rate limiter doesn't yet have a Redis
backend at all.

## 4. Assumptions Made During Ambiguous-Requirement Resolution

The plan's own designated ambiguous scenario — "make the service more secure" — is the concrete
worked example; see [`scenarios/ambiguous.md`](scenarios/ambiguous.md) for the full trace. In
summary: the Requirement Agent's heuristic (mock mode) surfaces three concrete interpretations
(rate limiting, alias entropy, redirect allowlisting) and defaults to rate limiting, on the
stated assumption that automated abuse/enumeration is the most common and highest-value threat
to address first, with the least behavior change to existing legitimate traffic. That default
was then subject to human review at Gate 2 (approved, with reasoning recorded in the transcript)
rather than applied silently.

A second, structural assumption is named directly in `scenarios/ambiguous.md` rather than
smoothed over: the plan's wording says a human "selects scope at Gate 0/1," but Gates 0 and 1
are automated by design (plan §3.3 is explicit about this). The actual human checkpoint for
scope is Gate 2, reviewing the *consequence* of the Requirement Agent's chosen interpretation,
not the interpretation label itself. If a re-plan ever needed to reconsider the interpretation
rather than the architecture, the current re-plan routing (back to Planning, not Requirement)
doesn't support that — see Known Limitations below.

## 5. Known Limitations and a Production Hardening Path

In rough priority order for a follow-up pass:

1. **Re-plan doesn't route back to Requirement.** All three re-plan checkpoints (Gates 2/3/4)
   loop back to Planning. If the *interpretation* of an ambiguous requirement turns out to be
   wrong (not just the architecture or implementation), there's no automated path back to
   Requirement to reconsider it — a human would need to start a fresh run.
2. **Coding Agent is single-file.** See §3.2.
3. **No distributed rate limiting or multi-instance cache invalidation.** See §3.5. Both are
   isolated, well-documented gaps with a clear next step (Redis-backed implementations behind
   the same interface), not silent ones.
4. **No real live-LLM run in this environment.** Every automated test and all three Phase 13
   scenario transcripts ran in mock mode, since no `ANTHROPIC_API_KEY` is configured here. The
   live code path is covered by unit tests that simulate live responses, and by code review, but
   not by an actual end-to-end live run producing a real multi-agent LLM-authored diff.
5. **In-memory LangGraph checkpointer.** `InMemorySaver` means a paused run (mid-approval-gate)
   doesn't survive a process restart. A durable checkpointer (SQLite- or Postgres-backed,
   LangGraph supports both) is a small, well-scoped change if runs need to survive restarts.
6. **OpenTelemetry exports to console only.** Real deployment would swap in an OTLP exporter —
   isolated to one function (`app/tracing.py`'s `_provider()`) by design, so this is a one-line
   change, not a refactor.
7. **No authentication/authorization anywhere** — neither on the URL shortener API nor on the
   orchestrator's `start_run`/`resume_run`/observability endpoints. Fine for this assignment's
   scope; a real deployment would need at minimum to gate who can approve Gates 2/5/6.

## 6. Testing Approach

165 tests, 99% combined line coverage across `app/` and `orchestrator/` (see `pytest
--cov=app --cov=orchestrator --cov-report=term-missing`). `tests/unit/` exercises services,
agents, and infrastructure modules directly with mocked boundaries (LLM calls, filesystem,
settings); `tests/integration/` drives the real FastAPI app via `TestClient` and the real
LangGraph graph via `start_run`/`resume_run`, including multi-gate interactive pause/resume
sequences, the bounded re-plan → safe-stop loop, and rollback of a real (temp-directory) file.
Concurrency claims (the click-counter fix) are validated with real multi-threaded workloads
against real SQLite sessions, not simulated. No test in this repository requires network access,
a real LLM, or Redis — every external dependency has a working local/mock default.
