from __future__ import annotations

from app.config import get_settings


def is_live() -> bool:
    return bool(get_settings().anthropic_api_key)


def call_llm(system: str, prompt: str, *, max_tokens: int = 1024) -> str:
    """Calls the configured Anthropic model and returns its text response.

    Raises RuntimeError if no API key is configured or the call fails.
    Callers own the fallback: each agent defines its own deterministic
    heuristic to use when the LLM is unavailable (see Section 3.4's
    Fallback control), rather than this module guessing a generic mock.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.llm_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in message.content if block.type == "text")
