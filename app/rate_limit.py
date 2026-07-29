"""Per-client-IP rate limiting for the abuse-prone endpoints (create,
redirect). In-process fixed-window counters, mirroring app/cache.py's
singleton-factory shape - fine for a single instance, but (like the
in-process cache) doesn't share state across multiple instances. A
Redis-backed limiter would be the natural next step for a multi-instance
deployment; not built here since REDIS_URL isn't guaranteed configured
and a correct distributed limiter is more than this scope calls for.
"""

import time
from threading import Lock

from fastapi import HTTPException, Request

from app.config import get_settings


class FixedWindowRateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: dict[tuple[str, int], int] = {}

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> None:
        """Raises HTTPException(429) if `key` has exceeded `limit` hits in
        the current fixed window. `limit <= 0` disables the check."""
        if limit <= 0:
            return

        window = int(time.time()) // window_seconds
        window_key = (key, window)

        with self._lock:
            count = self._counts.get(window_key, 0) + 1
            self._counts[window_key] = count
            if len(self._counts) > 10_000:
                # Opportunistic cleanup: drop any window older than the
                # current one rather than tracking a separate TTL per
                # entry - a fixed window's entries are only ever read
                # again within the same window.
                self._counts = {k: v for k, v in self._counts.items() if k[1] >= window}

        if count > limit:
            raise HTTPException(
                status_code=429,
                detail=f"rate limit exceeded ({limit}/min); try again shortly",
            )


_limiter: FixedWindowRateLimiter | None = None


def get_rate_limiter() -> FixedWindowRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = FixedWindowRateLimiter()
    return _limiter


def reset_rate_limiter() -> None:
    """Test-only: clears the singleton so counts don't leak between tests
    that share the same process."""
    global _limiter
    _limiter = None


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce_shorten_rate_limit(request: Request) -> None:
    settings = get_settings()
    get_rate_limiter().hit(
        f"shorten:{_client_key(request)}", settings.rate_limit_shorten_per_minute
    )


def enforce_redirect_rate_limit(request: Request) -> None:
    settings = get_settings()
    get_rate_limiter().hit(
        f"redirect:{_client_key(request)}", settings.rate_limit_redirect_per_minute
    )
