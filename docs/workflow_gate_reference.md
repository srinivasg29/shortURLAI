# Workflow / Gate Reference

The orchestrator (`orchestrator/graph.py`) is a single LangGraph `StateGraph`:

```
requirement → planning → architecture → coding → { testing, documentation } → gate4_sync → review → release
                              ↑                        ↑                          ↑
                        (Gate 2 fail)             (Gate 3 fail)              (Gate 4 fail)
                              └──────────── replan_node / safe_stop_node ─────────┘
```

Every node's output is appended (never overwritten) to `state["gate_log"]` and, via
`orchestrator/audit.py`, to the durable JSONL audit log at `AUDIT_LOG_PATH`.

## Gates

| Gate | Node | Exit criteria | Type | Re-plan checkpoint? |
|---|---|---|---|---|
| 0 | `requirement` | Intake normalized, ambiguity flagged | Automated | — |
| 1 | `planning` | Task graph + dependencies set (acyclic, no duplicate ids, all `depends_on` resolve) | Automated | — |
| 2 | `architecture` | **HUMAN APPROVAL: design** | Human (`interrupt()`) | Yes — rejection routes to `replan_node` |
| 3 | `coding` | Build + static checks pass (`ruff check`, only when a change was actually applied) | Automated | Yes |
| 4 | `gate4_sync` | SYNC: tests pass AND docs complete | Automated | Yes (stands in for "Testing" — see README) |
| 5 | `review` | **HUMAN APPROVAL: quality sign-off** | Human (`interrupt()`) | No |
| 6 | `release` | **HUMAN APPROVAL: release** | Human (`interrupt()`) | No |

`AUTO_APPROVE=1` skips the interactive pause at Gates 2/5/6, but Gates 5 and 6 are still
conditional, not a rubber stamp: Gate 5 only auto-passes if Gates 3 and 4 both passed; Gate 6
only auto-passes if *every* gate in the log passed.

## Controls (Section 3.4 of the plan)

| Control | Where | Behavior |
|---|---|---|
| **Retry** | `orchestrator/llm.py: call_llm` | Same call, same inputs, retried up to `MAX_RETRIES` (2) times before raising. Logged per attempt as an `llm_retry` audit event. |
| **Fallback** | Every agent's `run()` | On a raised (retry-exhausted) LLM failure, or no `ANTHROPIC_API_KEY` at all, falls back to a deterministic heuristic specific to that agent (e.g. `planning.default_task_graph`, `documentation._template_entry`). |
| **Rollback** | `orchestrator/agents/safe_stop.py` → `coding.rollback_last_applied()` | Restores the most recent applied `code_diffs` entry's `before` content to disk. Runs automatically at safe-stop, not gated on human sign-off. |
| **Safe-stop** | `orchestrator/agents/safe_stop.py` | Triggered when `replan_count` reaches `MAX_REPLANS` (2) at any of Gates 2/3/4. Rolls back, sets `state["safe_stopped"]`/`state["safe_stop_reason"]`, and (unless `AUTO_APPROVE`) pauses with an `interrupt()` notification rather than an approval request. |

## Re-plan vs. retry

A **retry** re-runs the same node on the same inputs (transient-failure recovery, scoped to a
single LLM call). A **re-plan** changes the task graph itself: `replan_node`
(`orchestrator/agents/replan.py`) reads the failing gate's detail, appends a `replan_log` entry,
and routes back to `planning`, which reads that reason and inserts a `remediate` task naming the
specific failure — so a second attempt is a genuine plan change, not a mechanical loop.

## State schema

`orchestrator/state.py`'s `OrchestratorState` is the single object threaded through every node.
List-valued fields (`gate_log`, `replan_log`, `architecture_decisions`, `code_diffs`,
`test_results`, `doc_diffs`) use an `operator.add` reducer, so parallel branches (Testing,
Documentation) and repeated re-plan loops all *append* to the same lineage rather than
clobbering each other's writes. Scalar fields (`llm_mode`, `replan_count`, `safe_stopped`,
`released`, ...) use ordinary last-write-wins semantics — a node that returns a dict without a
given key leaves that key's current value untouched, which is what lets `llm_mode` only ever be
*downgraded* to `"mock"` by a later node, never upgraded back to `"live"` on its behalf.

## See also

- [`README.md`](../README.md) — narrative walkthrough of each agent and the reasoning behind
  each design decision (why `gate4_sync` stands in for Testing, why a router can return a list
  of targets, etc.).
- [`observability/README.md`](../observability/README.md) — Prometheus/Grafana/tracing wiring.
- [`scenarios/`](../scenarios/) — three real runs through this graph (greenfield, brownfield,
  ambiguous), each with a committed audit-log transcript.
- [`FINAL_ENGINEERING_SUMMARY.md`](../FINAL_ENGINEERING_SUMMARY.md) — rationale, risks/trade-offs,
  assumptions, and known limitations.
