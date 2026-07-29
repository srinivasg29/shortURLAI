# Scenario: Ambiguous Requirement — "Make It More Secure"

**Requirement (raw input to the orchestrator):**
> make the service more secure

The plan's designated ambiguous scenario. What it's meant to demonstrate: "Requirement Agent
surfaces the ambiguity, proposes 2–3 concrete interpretations (rate limiting, alias entropy,
redirect allowlisting), and a human selects scope at Gate 0/1 before planning proceeds."

## 1. Requirement Agent's output

`orchestrator/agents/requirement.py`'s heuristic (mock mode — no `ANTHROPIC_API_KEY` in this
environment) recognizes this exact phrase and returns, verbatim, from the actual run:

```
identified_ambiguities:
 - Rate limiting on create/redirect endpoints to blunt abuse and enumeration
 - Higher-entropy short codes to make guessing/scanning codes impractical
 - Redirect target allowlisting/denylisting to block malicious destinations

normalized_spec: Requirement is underspecified. Pending human confirmation at Gate 0/1,
defaulting to rate limiting on POST /api/shorten and GET /{code} as the concrete scope, since it
addresses the most common abuse vector (automated link creation / scanning) with the least
behavior change.
```

That's the plan's 2–3 concrete interpretations, produced without an LLM call, plus a defensible
default with its reasoning stated explicitly rather than picked silently.

**One honest gap, named directly rather than glossed over:** the plan's wording says a human
selects scope "at Gate 0/1." In this implementation, Gates 0 and 1 are automated by design
(Section 3.3 of the plan is explicit: "Gates 0, 1, 3, and 4 are automated"), so there's no
interactive pause at that point — the Requirement Agent picks the default and states its
reasoning, and the first human checkpoint is Gate 2 (Architecture), where the human reviews the
resulting decisions and can reject them (which routes back to Planning — see
[`scenarios/brownfield.md`](brownfield.md) and the Phase 11 re-planning tests for that path).
That's a real, if partial, substitute for "selecting scope" — the human is reviewing the
consequence of the chosen interpretation, not the interpretation label itself, and if a run's
re-plan loop needed to reconsider the *interpretation* rather than the *architecture*, the
current design doesn't route back through Requirement Agent to do that. Worth flagging as a
known limitation rather than quietly working around it.

## 2. Orchestration path

| Gate | Node | Result | Approver |
|---|---|---|---|
| 0 | requirement_agent | pass | system (automated) — 3 ambiguities flagged, default scope stated |
| 1 | planning_agent | pass | system (automated) |
| 2 | architecture_agent | **pass** | human:sri — *"Agreed with the Requirement Agent default: rate limiting is the highest-value, lowest-risk interpretation of 'more secure' here — it directly blunts the automated-abuse threat model without touching redirect semantics. Alias entropy and redirect allowlisting are reasonable follow-ups but out of scope for this change. Approved."* |
| 3–4 | coding / gate4_sync | pass | system (automated) |
| 5 | review_agent | **pass** | human:sri — *"Verified: 20/min on create (tighter, since it's a write with lasting effect and the more common abuse vector) vs 120/min on redirect (a read most legitimate traffic depends on). Both configurable via env vars, both disableable via 0 for environments that front this with an edge-level limiter instead. Approved."* |
| 6 | release_readiness_agent | **pass** | human:sri — *"Released as part of the phase-13-ambiguous-rate-limiting PR."* |

`released: true`. Transcript: [`transcripts/ambiguous_rate_limiting_audit.jsonl`](transcripts/ambiguous_rate_limiting_audit.jsonl),
[`transcripts/ambiguous_rate_limiting_final_state.json`](transcripts/ambiguous_rate_limiting_final_state.json).

`code_diffs[0].path` resolved to `app/routers/shorten.py` (`codebase_map.py` matches
`"rate limit"` there) — a reasonable single-file target, though the real change (below) touches
more than one file, same known single-file-per-run limitation noted in the other two scenarios.
As before, Coding/Testing/Documentation ran in mock mode (`applied: false`); the real
implementation ships directly in this PR.

## 3. What actually shipped (this PR)

- **`app/rate_limit.py`** (new) — `FixedWindowRateLimiter`: per-key fixed-window counter,
  in-process (mirrors `app/cache.py`'s singleton-factory shape and its honest limitation — no
  shared state across multiple instances; a Redis-backed limiter is the natural next step for a
  multi-instance deployment, not built here since `REDIS_URL` isn't guaranteed configured).
  `enforce_shorten_rate_limit` / `enforce_redirect_rate_limit` key by client IP and raise
  `HTTPException(429)` once the per-minute budget set in `app/config.py` is exceeded.
- **`app/config.py`** — `rate_limit_shorten_per_minute` (default 20) and
  `rate_limit_redirect_per_minute` (default 120), deliberately asymmetric: creating a link is a
  write with lasting effect and the more common abuse vector; following one is a read most
  legitimate traffic depends on. `0` disables the check.
- **`app/routers/shorten.py`** / **`app/routers/redirect.py`** — wired as FastAPI
  `dependencies=[Depends(...)]`, so a 429 is raised before the handler body runs at all.

## 4. Validation

- `tests/unit/test_rate_limit.py` — within-limit passes, over-limit raises 429, keys tracked
  independently, `limit <= 0` disables the check, and the opportunistic old-window cleanup
  (triggered once the counter table exceeds 10k entries) actually drops stale entries.
- `tests/integration/test_api_flow.py` — real 429s through the actual endpoints (`POST
  /api/shorten` and `GET /{code}`) once the configured limit is exceeded, and confirms `0`
  truly disables enforcement rather than just raising the threshold.
- **Test isolation**: the limiter is a module-level singleton, so its counts persist across
  tests in the same process unless reset — added an autouse `_reset_rate_limiter` fixture
  (`tests/conftest.py`) clearing it before/after every test, the same pattern already used for
  `_clean_tables`. Without it, unrelated tests sharing the TestClient's default IP would have
  started tripping each other's limits.
- Manually verified against a running `uvicorn` instance (3 requests allowed, 4th returns 429
  with `RATE_LIMIT_SHORTEN_PER_MINUTE=3`) before writing this up.
