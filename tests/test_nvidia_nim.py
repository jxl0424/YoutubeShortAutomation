"""Tests for the NVIDIA NIM adapter with an injected fake openai client."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trend_intelligence.config.settings import LLMConfig
from trend_intelligence.domain.exceptions import InvalidLLMResponseError, LLMError
from trend_intelligence.intelligence.llm.nvidia_nim import NvidiaNimProvider
from trend_intelligence.intelligence.schemas import TrendAnalysisBatch

VALID_JSON = (
    '{"analyses": [{"cluster_id": "c1", "keep": true, '
    '"refined_title": "Mars landing"}]}'
)


def _response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class FakeClient:
    def __init__(self, content=None, exc=None):
        self._content = content
        self._exc = exc
        self.last_kwargs = None
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._exc is not None:
            raise self._exc
        return _response(self._content)


def _provider(client):
    return NvidiaNimProvider(LLMConfig(api_key="test-key"), client=client)


def test_parses_valid_json():
    provider = _provider(FakeClient(content=VALID_JSON))
    result = provider.generate_structured(
        system="s", user="u", schema=TrendAnalysisBatch
    )
    assert isinstance(result, TrendAnalysisBatch)
    assert result.analyses[0].cluster_id == "c1"


def test_strips_markdown_fences():
    fenced = f"```json\n{VALID_JSON}\n```"
    provider = _provider(FakeClient(content=fenced))
    result = provider.generate_structured(
        system="s", user="u", schema=TrendAnalysisBatch
    )
    assert result.analyses[0].refined_title == "Mars landing"


def test_invalid_json_raises():
    provider = _provider(FakeClient(content="not json at all"))
    with pytest.raises(InvalidLLMResponseError):
        provider.generate_structured(system="s", user="u", schema=TrendAnalysisBatch)


def test_api_error_becomes_llm_error():
    provider = _provider(FakeClient(exc=RuntimeError("connection reset")))
    with pytest.raises(LLMError):
        provider.generate_structured(system="s", user="u", schema=TrendAnalysisBatch)


def test_missing_api_key_raises_without_client():
    provider = NvidiaNimProvider(LLMConfig(api_key=None))  # no injected client
    with pytest.raises(LLMError):
        provider.generate_structured(system="s", user="u", schema=TrendAnalysisBatch)


def test_request_uses_configured_model():
    client = FakeClient(content=VALID_JSON)
    provider = NvidiaNimProvider(
        LLMConfig(api_key="k", model="meta/llama-3.1-70b-instruct"), client=client
    )
    provider.generate_structured(system="s", user="u", schema=TrendAnalysisBatch)
    assert client.last_kwargs["model"] == "meta/llama-3.1-70b-instruct"
    assert client.last_kwargs["response_format"] == {"type": "json_object"}
