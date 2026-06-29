"""NVIDIA NIM LLM adapter (OpenAI-compatible API).

Talks to ``https://integrate.api.nvidia.com/v1`` using the ``openai`` SDK and
parses the model's JSON output into the requested Pydantic schema. The openai
client is injectable so tests never touch the network.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from ...config.settings import LLMConfig
from ...domain.exceptions import InvalidLLMResponseError, LLMError
from ...logging.setup import get_logger
from .base import LLMProvider

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _extract_json(text: str) -> str:
    """Strip markdown fences and isolate the outermost JSON object."""
    text = _FENCE_RE.sub("", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise InvalidLLMResponseError("no JSON object found in LLM response")
    return text[start : end + 1]


class NvidiaNimProvider(LLMProvider):
    def __init__(self, config: LLMConfig, *, client: Any | None = None) -> None:
        self._config = config
        self._client = client
        self._logger = get_logger("intelligence.llm.nvidia_nim")

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._config.api_key:
                raise LLMError(
                    f"NVIDIA NIM API key missing (set env {self._config.api_key_env})"
                )
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self._config.base_url,
                api_key=self._config.api_key,
                timeout=self._config.timeout_seconds,
            )
        return self._client

    def generate_structured(
        self, *, system: str, user: str, schema: type[BaseModel]
    ) -> BaseModel:
        client = self._get_client()
        try:
            response = client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # network / API errors → retryable LLMError
            raise LLMError(f"NVIDIA NIM request failed: {exc}") from exc

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise InvalidLLMResponseError(f"malformed LLM response: {exc}") from exc

        raw = _extract_json(content or "")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidLLMResponseError(f"invalid JSON from LLM: {exc}") from exc

        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            raise InvalidLLMResponseError(
                f"LLM JSON did not match schema: {exc}"
            ) from exc
