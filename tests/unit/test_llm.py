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
