# Scenario: Brownfield — Thread-Safe Click Counter

**Requirement (raw input to the orchestrator):**
> Refactor the analytics click-counter for thread-safety under concurrent redirects.

The plan's designated brownfield scenario. What it's meant to demonstrate: "Codebase Reasoning:
identify impacted module (analytics service), data flow (Redis counter → DB sync), and
regression risk before changing it."

One honest note before the rest of this doc: the plan's phrasing (`"Redis counter → DB sync"`)
describes a data flow this codebase doesn't actually have — there's no separate analytics
service or Redis-backed counter, clicks are tracked directly on the `ShortUrl` row. Section 2
below describes the *real* data flow rather than retrofitting a fictional one to match the
plan's wording.

## 1. Codebase reasoning (impacted module + data flow + regression risk)

**Impacted module.** `orchestrator/codebase_map.py`'s keyword heuristic maps `"click"`,
`"counter"`, `"analytics"` → `app/services/shortener.py`, without an LLM call. That's exactly
where `record_click()` lives, and where the real fix landed (see below) — the transcript
(`code_diffs[0].path`) confirms this matched at run time, not just in the keyword table.

**Data flow (as it actually exists, pre-fix):**

```
GET /{code}  (app/routers/redirect.py)
  → BackgroundTasks.add_task(_record_click_by_code, code)
      → opens its OWN SessionLocal() — a new, independent DB session per task
      → get_by_code(db, code)         # SELECT, loads a ShortUrl into THIS session
      → record_click(db, short_url)   # short_url.click_count += 1 in Python, then commit
```

**Regression risk, identified before changing anything:** every concurrent redirect for the
same code spawns its own background task with its own session and its own in-memory copy of
the row. Two tasks can both `SELECT` `click_count = N` before either commits its `UPDATE` — both
then write back `N + 1`. One increment is silently lost. This is a textbook lost-update race,
and it gets worse, not better, under load — the traffic pattern most likely to trigger it is
exactly the one a click counter exists to measure.

## 2. Orchestration path

Driven interactively through all seven gates:

| Gate | Node | Result | Approver |
|---|---|---|---|
| 0–1 | requirement / planning | pass | system (automated) |
| 2 | architecture_agent | **pass** | human:sri — *"Confirmed: no new external dependency needed. Pushing the increment into a single atomic UPDATE statement is the right fix — simpler and more robust than adding a lock or a Redis counter for this scale. Approved."* |
| 3–4 | coding / gate4_sync | pass | system (automated) |
| 5 | review_agent | **pass** | human:sri — *"Verified the fix against a real concurrency regression test (20 threads × 10 clicks each, separate DB sessions per thread, matching the real background-task pattern) — exact count, no lost updates. Also reproduced the original bug in isolation: the naive read-modify-write lost ~93% of clicks (14/200) under the same workload. Approved."* |
| 6 | release_readiness_agent | **pass** | human:sri — *"Released as part of the phase-13-brownfield-click-counter PR."* |

`released: true`. Transcript: [`transcripts/brownfield_click_counter_audit.jsonl`](transcripts/brownfield_click_counter_audit.jsonl),
[`transcripts/brownfield_click_counter_final_state.json`](transcripts/brownfield_click_counter_final_state.json).

As in the greenfield scenario, Coding/Testing/Documentation ran in mock mode (no
`ANTHROPIC_API_KEY` in this environment) — `code_diffs[0].applied == false`. The real fix ships
directly in this PR.

## 3. What actually shipped (this PR)

**`app/services/shortener.py` — `record_click()`:** replaced the read-modify-write with a single
atomic `UPDATE short_urls SET click_count = click_count + 1, last_clicked_at = ? WHERE code = ?`.
The `+ 1` now happens inside the database engine, which is what actually owns the atomicity
guarantee — the application no longer needs to hold a consistent in-memory copy of the row
across a read and a write. The function's signature changed from taking a loaded `ShortUrl` to
taking a bare `code: str`, which also removes a `SELECT` from the hot path: callers no longer
need to fetch the row before recording a click.

**`app/routers/redirect.py` — `_record_click_by_code()`:** simplified accordingly — one call
instead of a fetch-then-update pair.

## 4. Validation (and proving the bug was real)

`tests/unit/test_shortener_service.py::test_record_click_has_no_lost_updates_under_concurrent_redirects`
drives 20 threads × 10 clicks each against the same code, each thread opening its own session
(mirroring the real background-task pattern exactly, not a simplified stand-in), and asserts the
final count is exact.

Before writing that test, the regression it guards against was confirmed empirically, not just
argued: the original read-modify-write implementation, run through the identical 20×10
concurrent workload, produced **14 recorded clicks out of 200** — a ~93% loss rate. The fix,
under the same workload, produces exactly 200. That comparison is the concrete "regression risk"
validation the brownfield scenario calls for.

Also updated: `test_record_click_increments_counter` (now calls by `code` and re-fetches via
`db.refresh()` to observe the DB-side update) and a new
`test_record_click_on_unknown_code_is_a_safe_no_op` (an `UPDATE` matching zero rows must not
raise, unlike the old fetch-then-mutate version which needed an explicit `is not None` guard).
