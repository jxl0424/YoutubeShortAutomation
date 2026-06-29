"""Fallback LLM chain — tries providers in order until one succeeds.

This is how the spec's "primary Gemini Flash, fallback Groq/OpenRouter" resilience
is realised: each provider is tried in turn; a failure moves to the next. If all
fail, the last error is surfaced.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from trend_intelligence.domain.exceptions import LLMError
from trend_intelligence.logging.setup import get_logger

from ...domain.interfaces import LLMProvider


class FallbackLLM(LLMProvider):
    def __init__(self, providers: Sequence[LLMProvider]) -> None:
        if not providers:
            raise LLMError("FallbackLLM requires at least one provider")
        self._providers = list(providers)
        self._logger = get_logger("shorts.llm.fallback")

    def generate_structured(
        self, *, system: str, user: str, schema: type[BaseModel]
    ) -> BaseModel:
        last_error: Exception | None = None
        for provider in self._providers:
            name = getattr(provider, "name", type(provider).__name__)
            try:
                return provider.generate_structured(
                    system=system, user=user, schema=schema
                )
            except LLMError as exc:
                last_error = exc
                self._logger.warning(
                    "llm_provider_failed", provider=name, error=str(exc)
                )
        raise LLMError(f"all LLM providers failed; last error: {last_error}")
