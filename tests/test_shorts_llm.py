"""Tests for the Stage 2 LLM layer: OpenAI-compatible adapter, fallback, factory."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from shorts.config.settings import ScriptConfig
from shorts.domain.exceptions import ScriptGenerationError
from shorts.domain.interfaces import LLMProvider
from shorts.providers.llm.factory import build_script_llm
from shorts.providers.llm.fallback import FallbackLLM
from shorts.providers.llm.openai_compatible import OpenAICompatibleLLM
from trend_intelligence.domain.exceptions import InvalidLLMResponseError, LLMError

VALID = '{"hello": "world"}'


class Out(BaseModel):
    hello: str


def _response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class FakeClient:
    def __init__(self, content=None, exc=None):
        self._content = content
        self._exc = exc
        self.kwargs = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        if self._exc is not None:
            raise self._exc
        return _response(self._content)


def _llm(client, **kw):
    return OpenAICompatibleLLM(
        base_url="http://x", api_key="k", model="m", client=client, **kw
    )


# --- OpenAICompatibleLLM --------------------------------------------------- #
def test_parses_valid_json():
    result = _llm(FakeClient(content=VALID)).generate_structured(
        system="s", user="u", schema=Out
    )
    assert isinstance(result, Out)
    assert result.hello == "world"


def test_strips_markdown_fences():
    result = _llm(FakeClient(content=f"```json\n{VALID}\n```")).generate_structured(
        system="s", user="u", schema=Out
    )
    assert result.hello == "world"


def test_invalid_json_raises():
    with pytest.raises(InvalidLLMResponseError):
        _llm(FakeClient(content="not json")).generate_structured(
            system="s", user="u", schema=Out
        )


def test_api_error_becomes_llm_error():
    with pytest.raises(LLMError):
        _llm(FakeClient(exc=RuntimeError("boom"))).generate_structured(
            system="s", user="u", schema=Out
        )


def test_missing_key_raises():
    provider = OpenAICompatibleLLM(base_url="http://x", api_key=None, model="m")
    with pytest.raises(LLMError):
        provider.generate_structured(system="s", user="u", schema=Out)


def test_json_mode_can_be_disabled():
    client = FakeClient(content=VALID)
    _llm(client, use_json_mode=False).generate_structured(
        system="s", user="u", schema=Out
    )
    assert "response_format" not in client.kwargs


# --- FallbackLLM ----------------------------------------------------------- #
class StubLLM(LLMProvider):
    def __init__(self, *, result=None, exc=None, name="stub"):
        self.name = name
        self._result = result
        self._exc = exc
        self.calls = 0

    def generate_structured(self, *, system, user, schema):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result


def test_fallback_uses_second_when_first_fails():
    first = StubLLM(exc=LLMError("down"), name="a")
    second = StubLLM(result=Out(hello="ok"), name="b")
    result = FallbackLLM([first, second]).generate_structured(
        system="s", user="u", schema=Out
    )
    assert result.hello == "ok"
    assert first.calls == 1 and second.calls == 1


def test_fallback_all_fail_raises():
    chain = FallbackLLM([StubLLM(exc=LLMError("1")), StubLLM(exc=LLMError("2"))])
    with pytest.raises(LLMError):
        chain.generate_structured(system="s", user="u", schema=Out)


def test_fallback_requires_providers():
    with pytest.raises(LLMError):
        FallbackLLM([])


# --- factory --------------------------------------------------------------- #
def test_factory_builds_chain_with_primary_key():
    config = ScriptConfig(provider="gemini_flash", api_key="gem", fallback_providers=[])
    llm = build_script_llm(config)
    assert isinstance(llm, FallbackLLM)
    assert llm._providers[0].name == "gemini_flash"


def test_factory_passes_timeout_to_providers():
    config = ScriptConfig(
        provider="gemini_flash",
        api_key="gem",
        fallback_providers=[],
        timeout_seconds=99.0,
    )
    llm = build_script_llm(config)
    assert llm._providers[0]._timeout == 99.0


def test_factory_skips_providers_without_keys(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    config = ScriptConfig(
        provider="gemini_flash",
        api_key=None,  # no primary key
        fallback_providers=["groq", "openrouter"],
    )
    llm = build_script_llm(config)
    names = [p.name for p in llm._providers]
    assert names == ["openrouter"]  # gemini + groq skipped (no keys)


def test_factory_raises_when_no_keys(monkeypatch):
    for env in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "NVIDIA_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)
    config = ScriptConfig(api_key=None, fallback_providers=["groq"])
    with pytest.raises(ScriptGenerationError):
        build_script_llm(config)
