import pytest
from fastapi import HTTPException

from app.rate_limit import FixedWindowRateLimiter


def test_hit_allows_requests_within_limit():
    limiter = FixedWindowRateLimiter()
    for _ in range(5):
        limiter.hit("k", limit=5)


def test_hit_raises_429_once_limit_exceeded():
    limiter = FixedWindowRateLimiter()
    for _ in range(5):
        limiter.hit("k", limit=5)

    with pytest.raises(HTTPException) as exc_info:
        limiter.hit("k", limit=5)
    assert exc_info.value.status_code == 429


def test_hit_tracks_keys_independently():
    limiter = FixedWindowRateLimiter()
    for _ in range(5):
        limiter.hit("a", limit=5)

    # A different key has its own budget, unaffected by "a" being exhausted.
    limiter.hit("b", limit=5)


def test_limit_of_zero_disables_the_check():
    limiter = FixedWindowRateLimiter()
    for _ in range(1000):
        limiter.hit("k", limit=0)


def test_negative_limit_disables_the_check():
    limiter = FixedWindowRateLimiter()
    limiter.hit("k", limit=-1)


def test_hit_cleans_up_old_windows_when_table_grows_large(monkeypatch):
    import app.rate_limit as rate_limit_module

    limiter = FixedWindowRateLimiter()
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: 0)
    for i in range(10_001):
        limiter.hit(f"k{i}", limit=100_000, window_seconds=60)

    monkeypatch.setattr(rate_limit_module.time, "time", lambda: 120)
    limiter.hit("new-window-key", limit=5)

    assert all(k[1] == 2 for k in limiter._counts)
