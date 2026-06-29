"""Deterministic mock LLM provider for tests and offline runs.

By default it parses the analyzer's user prompt (a JSON ``{"trends": [...]}``
payload) and echoes one analysis per trend, so the full analyzer flow can be
exercised without any network access. Knobs allow simulating failures and
custom keep decisions.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from ...domain.exceptions import InvalidLLMResponseError
from .base import LLMProvider


class MockLLMProvider(LLMProvider):
    def __init__(
        self,
        *,
        keep_filter: Callable[[dict[str, Any]], bool] | None = None,
        raise_times: int = 0,
        exc: Exception | None = None,
        responder: Callable[[str, str, type[BaseModel]], BaseModel] | None = None,
    ) -> None:
        self._keep_filter = keep_filter
        self._raise_times = raise_times
        self._exc = exc or InvalidLLMResponseError("mock LLM failure")
        self._responder = responder
        self.calls = 0

    def generate_structured(
        self, *, system: str, user: str, schema: type[BaseModel]
    ) -> BaseModel:
        self.calls += 1
        if self.calls <= self._raise_times:
            raise self._exc
        if self._responder is not None:
            return self._responder(system, user, schema)

        trends = json.loads(user).get("trends", [])
        analyses = []
        for trend in trends:
            title = trend.get("title", "")
            keep = True if self._keep_filter is None else self._keep_filter(trend)
            analyses.append(
                {
                    "cluster_id": trend["cluster_id"],
                    "keep": keep,
                    "refined_title": title,
                    "emerging_theme": "emerging theme",
                    "estimated_audience_interest": 0.7,
                    "video_angles": [f"What you didn't know about {title}"],
                    "hooks": [f"Here's why {title} matters"],
                    "target_audience": "general",
                    "recommended_category": "other",
                    "is_safe": True,
                    "safety_flags": [],
                    "educational_value": 0.6,
                    "entertainment_value": 0.6,
                    "visual_potential": 0.6,
                    "ai_confidence": 0.8,
                }
            )
        return schema.model_validate({"analyses": analyses})
