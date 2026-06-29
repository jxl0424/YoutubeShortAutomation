"""Generic OpenAI-compatible LLM adapter.

Gemini (via its OpenAI endpoint), Groq, OpenRouter and NVIDIA NIM all speak the
OpenAI chat-completions protocol, so one parameterised adapter covers them all —
only ``base_url`` and ``model`` differ. Reuses Stage 1's ``LLMProvider``
interface and error types. The client is injectable so tests never hit the API.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from trend_intelligence.domain.exceptions import InvalidLLMResponseError, LLMError

from ...domain.interfaces import LLMProvider

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _extract_json(text: str) -> str:
    text = _FENCE_RE.sub("", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise InvalidLLMResponseError("no JSON object found in LLM response")
    return text[start : end + 1]


class OpenAICompatibleLLM(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 30.0,
        name: str = "openai_compatible",
        use_json_mode: bool = True,
        client: Any | None = None,
    ) -> None:
        self.name = name
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._use_json_mode = use_json_mode
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise LLMError(f"{self.name}: API key missing")
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self._base_url, api_key=self._api_key, timeout=self._timeout
            )
        return self._client

    def generate_structured(
        self, *, system: str, user: str, schema: type[BaseModel]
    ) -> BaseModel:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if self._use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMError(f"{self.name} request failed: {exc}") from exc

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise InvalidLLMResponseError(
                f"{self.name}: malformed response: {exc}"
            ) from exc

        raw = _extract_json(content or "")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidLLMResponseError(f"{self.name}: invalid JSON: {exc}") from exc
        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            raise InvalidLLMResponseError(
                f"{self.name}: JSON did not match schema: {exc}"
            ) from exc
