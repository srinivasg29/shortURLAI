import time

from app.cache import InProcessTTLCache


def test_set_and_get():
    cache = InProcessTTLCache()
    cache.set("k", "v", ttl=60)
    assert cache.get("k") == "v"


def test_get_missing_key_returns_none():
    cache = InProcessTTLCache()
    assert cache.get("missing") is None


def test_expired_entry_returns_none():
    cache = InProcessTTLCache()
    cache.set("k", "v", ttl=0)
    time.sleep(0.01)
    assert cache.get("k") is None


def test_delete():
    cache = InProcessTTLCache()
    cache.set("k", "v")
    cache.delete("k")
    assert cache.get("k") is None
