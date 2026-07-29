from __future__ import annotations

import time

from app.config import get_settings
from orchestrator import audit

MAX_RETRIES = 2


def is_live() -> bool:
    return bool(get_settings().anthropic_api_key)


def call_llm(system: str, prompt: str, *, max_tokens: int = 1024, node: str = "unknown") -> str:
    """Calls the configured Anthropic model and returns its text response.

    Retries up to MAX_RETRIES times (same inputs, same call) on any failure
    before raising - this is the plan's Retry control. Only once retries are
    exhausted does the caller see an exception, at which point the agent's
    own except-block Fallback (a deterministic heuristic) takes over. Each
    failed attempt is logged as an llm_retry audit event so retry frequency
    is visible in the audit trail, independent of the eventual Fallback
    outcome.

    `node` labels which agent is calling, purely for observability (audit
    events, Section 8's "retry frequency ... per node" metric) - it has no
    effect on behavior.

    Raises RuntimeError immediately (no retries) if no API key is
    configured - that's a config problem, not a transient failure.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    last_error: Exception | None = None
    started = time.monotonic()
    for attempt in range(MAX_RETRIES + 1):
        try:
            message = client.messages.create(
                model=settings.llm_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = getattr(message, "usage", None)
            audit.append_event(
                {
                    "type": "llm_call",
                    "node": node,
                    "success": True,
                    "attempt": attempt + 1,
                    "latency_ms": round((time.monotonic() - started) * 1000, 1),
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "output_tokens": getattr(usage, "output_tokens", None),
                }
            )
            return "".join(block.text for block in message.content if block.type == "text")
        except Exception as exc:
            last_error = exc
            audit.append_event(
                {
                    "type": "llm_retry",
                    "node": node,
                    "attempt": attempt + 1,
                    "max_attempts": MAX_RETRIES + 1,
                    "error": str(exc),
                }
            )

    audit.append_event(
        {
            "type": "llm_call",
            "node": node,
            "success": False,
            "attempt": MAX_RETRIES + 1,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "input_tokens": None,
            "output_tokens": None,
        }
    )
    assert last_error is not None
    raise last_error
