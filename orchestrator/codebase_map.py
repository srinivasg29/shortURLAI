from __future__ import annotations

# Heuristic requirement/task text -> real source file. Doubles as the
# Codebase Reasoning capability for the brownfield scenario (identifying
# impacted modules without an LLM call) and as target-file selection for
# the Coding Agent.
_KEYWORD_TO_PATH: list[tuple[tuple[str, ...], str]] = [
    (("click", "counter", "analytics"), "app/services/shortener.py"),
    (("alias", "vanity", "collision", "custom code", "custom short"), "app/services/shortener.py"),
    (("rate limit", "throttle", "abuse"), "app/routers/shorten.py"),
    (("redirect",), "app/routers/redirect.py"),
    (("shorten", "create short", "endpoint"), "app/routers/shorten.py"),
    (("stats",), "app/routers/analytics.py"),
]


def identify_impacted_modules(text: str) -> list[str]:
    """Returns real source files likely impacted by the given requirement or
    task text, in match order, without duplicates. Empty if no keyword
    matched — callers must treat that as "unknown", not "no impact"."""
    lowered = text.lower()
    matches: list[str] = []
    for keywords, path in _KEYWORD_TO_PATH:
        if any(kw in lowered for kw in keywords) and path not in matches:
            matches.append(path)
    return matches
