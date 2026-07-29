"""Cache for the redirect hot path (code -> target_url).

Backed by Redis when REDIS_URL is set; otherwise falls back to a small
in-process TTL cache so local dev and tests work without a Redis instance.
"""

import time
from threading import Lock
from typing import Protocol

from app.config import get_settings

DEFAULT_TTL_SECONDS = 300


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int = DEFAULT_TTL_SECONDS) -> None: ...
    def delete(self, key: str) -> None: ...


class InProcessTTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}
        self._lock = Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at < time.monotonic():
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: str, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


class RedisCache:
    def __init__(self, redis_url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self._client.set(key, value, ex=ttl)

    def delete(self, key: str) -> None:
        self._client.delete(key)


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is not None:
        return _cache

    settings = get_settings()
    if settings.redis_url:
        _cache = RedisCache(settings.redis_url)
    else:
        _cache = InProcessTTLCache()
    return _cache
