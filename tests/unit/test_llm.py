import sys
import types

import pytest

from app.config import get_settings
from orchestrator import llm


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    yield
    get_settings.cache_clear()


def test_is_live_false_without_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()

    assert llm.is_live() is False


def test_is_live_true_with_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    get_settings.cache_clear()

    assert llm.is_live() is True


def test_call_llm_raises_without_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError):
        llm.call_llm("system", "prompt")


def test_call_llm_returns_text_from_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    get_settings.cache_clear()

    text_block = types.SimpleNamespace(type="text", text="hello from claude")

    class _FakeMessages:
        def create(self, **kwargs):
            return types.SimpleNamespace(content=[text_block])

    class _FakeAnthropic:
        def __init__(self, api_key):
            self.messages = _FakeMessages()

    fake_module = types.SimpleNamespace(Anthropic=_FakeAnthropic)
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    result = llm.call_llm("system", "prompt")

    assert result == "hello from claude"


def _install_flaky_client(monkeypatch, fail_count: int):
    """A fake Anthropic client whose .create() fails `fail_count` times
    before succeeding, so tests can drive llm.call_llm's retry loop
    deterministically."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    get_settings.cache_clear()

    calls = {"count": 0}
    text_block = types.SimpleNamespace(type="text", text="ok")

    class _FakeMessages:
        def create(self, **kwargs):
            calls["count"] += 1
            if calls["count"] <= fail_count:
                raise TimeoutError("transient")
            return types.SimpleNamespace(content=[text_block])

    class _FakeAnthropic:
        def __init__(self, api_key):
            self.messages = _FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_FakeAnthropic))
    return calls


def test_call_llm_retries_and_succeeds_within_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()
    calls = _install_flaky_client(monkeypatch, fail_count=llm.MAX_RETRIES)

    result = llm.call_llm("system", "prompt")

    assert result == "ok"
    assert calls["count"] == llm.MAX_RETRIES + 1


def test_call_llm_raises_after_exhausting_retries(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_settings.cache_clear()
    calls = _install_flaky_client(monkeypatch, fail_count=llm.MAX_RETRIES + 1)

    with pytest.raises(TimeoutError):
        llm.call_llm("system", "prompt")

    assert calls["count"] == llm.MAX_RETRIES + 1


def test_call_llm_logs_a_retry_audit_event_per_failed_attempt(monkeypatch, tmp_path):
    import json

    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    get_settings.cache_clear()
    _install_flaky_client(monkeypatch, fail_count=llm.MAX_RETRIES)

    llm.call_llm("system", "prompt")

    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    retry_events = [e for e in events if e["type"] == "llm_retry"]
    assert len(retry_events) == llm.MAX_RETRIES
    assert [e["attempt"] for e in retry_events] == list(range(1, llm.MAX_RETRIES + 1))
