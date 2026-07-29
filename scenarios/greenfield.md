# Scenario: Greenfield — Vanity Alias

**Requirement (raw input to the orchestrator):**
> Add a custom vanity-alias feature (user-supplied short code with collision handling).

This is the plan's designated greenfield scenario: "Full graph run start to finish, including
Gate 2 architecture approval for the new uniqueness constraint."

## 1. Decomposition

The Requirement Agent found nothing ambiguous here (no vague/underspecified language), so
`normalized_spec` passes through unchanged. The Planning Agent's `task_graph`:

```
design → implement → { test, document } → review
```

(the standard template — see `orchestrator/agents/planning.py:default_task_graph`).

## 2. Orchestration path

Full run through all seven gates, driven interactively (`AUTO_APPROVE` unset) so each human
checkpoint is a real pause/resume, not a rubber stamp:

| Gate | Node | Result | Approver |
|---|---|---|---|
| 0 | requirement_agent | pass | system (automated) |
| 1 | planning_agent | pass | system (automated) |
| 2 | architecture_agent | **pass** | human:sri — *"Reusing the existing ShortUrl schema and adding an optional custom_alias field is the right call — no new table needed. Approved."* |
| 3 | coding_agent | pass | system (automated) |
| 4 | gate4_sync | pass | system (automated) |
| 5 | review_agent | **pass** | human:sri — *"Reviewed the collision-handling logic (reserved-word check + uniqueness check + IntegrityError fallback for the race window) — matches what shipped in the real PR. Approved."* |
| 6 | release_readiness_agent | **pass** | human:sri — *"Released as part of the phase-13-greenfield-vanity-alias PR."* |

`released: true`. Full transcript: [`transcripts/greenfield_vanity_alias_audit.jsonl`](transcripts/greenfield_vanity_alias_audit.jsonl)
(raw audit log) and [`transcripts/greenfield_vanity_alias_final_state.json`](transcripts/greenfield_vanity_alias_final_state.json)
(final `OrchestratorState`, pretty-printed).

**Codebase reasoning, without an LLM call:** `orchestrator/codebase_map.py`'s keyword heuristic
correctly identified `app/services/shortener.py` as the file to change — matching where the real
implementation landed (see below) — from the requirement text alone (`"alias"`, `"collision"`
match the module's keyword table).

## 3. What actually shipped (this PR)

This environment has no `ANTHROPIC_API_KEY` configured, so the Coding/Testing/Documentation
agents ran in mock mode: `code_diffs[0].applied == false`, a labeled proposal rather than a real
edit (see [`README.md`](../README.md#coding-agent) for why that's a deliberate safety property,
not a shortcoming of this run). The actual feature — real code, reviewed the same way a live run
would produce it — is included directly in this PR:

- **`app/schemas.py`** — `ShortenRequest.custom_alias`: optional, 3–32 chars,
  `[A-Za-z0-9_-]+`, enforced by Pydantic before the service layer ever sees it.
- **`app/services/shortener.py`** — `_resolve_custom_alias()` checks the reserved-path list and
  DB uniqueness; `create_short_url()` uses it in place of random generation when supplied. The
  **collision handling** the requirement calls for has two layers: the optimistic pre-commit
  check (fast, covers the common case) and a `try/except IntegrityError` around the actual
  commit (catches the race where a concurrent request wins between the check and the insert) —
  both raise the same `AliasAlreadyTaken`, so callers see one consistent error regardless of
  which layer caught it.
- **`app/routers/shorten.py`** — maps `AliasAlreadyTaken` → `409 Conflict`.

## 4. Validation

- `tests/unit/test_shortener_service.py` — valid alias, taken alias, reserved-word alias,
  custom_alias short-circuiting random generation, and the concurrent-insert race path
  (`test_create_short_url_raises_alias_taken_on_concurrent_insert_race`, which forces the
  optimistic check to pass so the real `IntegrityError` path is what's under test).
- `tests/integration/test_api_flow.py` — end-to-end create → redirect via the vanity alias,
  409 on a duplicate, 422 on a malformed or too-short alias.
- Manually verified against a running `uvicorn` instance (create, redirect, duplicate rejection)
  before writing this up.
