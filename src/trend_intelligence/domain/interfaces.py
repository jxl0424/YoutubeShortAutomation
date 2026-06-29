"""Abstract interfaces (ports) the rest of the application depends on.

The dependency rule: application services depend on these abstractions, never
on concrete providers/adapters. Concrete implementations live in the
infrastructure layers (``providers/``, ``intelligence/llm/``, ``cache/``) and
are wired together by the composition root (``pipeline.py``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import BaseModel

from .models import (
    AggregatedTrend,
    RankedTrend,
    ScoreBreakdown,
    SelectedTopic,
    TrendAnalysis,
    TrendProviderResult,
    TrendQuery,
    TrendSource,
)


class TrendProvider(ABC):
    """Common interface every trend source must implement.

    Implementations normalize provider-specific responses into the shared
    domain models and must not raise on external failures — they return a
    ``TrendProviderResult`` with ``success=False`` instead.
    """

    #: The source category this provider represents.
    source: ClassVar[TrendSource]

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """Whether this provider should participate in discovery."""

    @abstractmethod
    def discover(self, query: TrendQuery) -> TrendProviderResult:
        """Discover trending topics for the given query."""


class LLMProvider(ABC):
    """Low-level structured-output interface for the configured LLM.

    Business logic (prompts, orchestration) lives in the intelligence layer so
    that swapping providers requires only a new adapter.
    """

    @abstractmethod
    def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        """Return an instance of ``schema`` parsed from the model's JSON output."""


class TrendCache(ABC):
    """Namespaced key/value cache with TTL. Storage-agnostic so a Redis/DB
    backend can replace the local implementation without touching callers."""

    @abstractmethod
    def get(self, namespace: str, key: str) -> Any | None:
        """Return the cached value, or ``None`` on miss/expiry."""

    @abstractmethod
    def set(
        self, namespace: str, key: str, value: Any, ttl: int | None = None
    ) -> None:
        """Store a JSON-serializable value with an optional TTL (seconds)."""

    @abstractmethod
    def invalidate(self, namespace: str, key: str | None = None) -> None:
        """Invalidate a single key, or the whole namespace when ``key`` is None."""


class ScoringStrategy(ABC):
    """Pluggable scoring algorithm. The whole strategy can be replaced via
    configuration without changing the scoring engine."""

    @abstractmethod
    def score(
        self,
        trend: AggregatedTrend,
        analysis: TrendAnalysis | None,
        weights: Mapping[str, float],
    ) -> ScoreBreakdown:
        """Combine multiple signals into a transparent score breakdown."""


class SelectionStrategy(ABC):
    """Pluggable topic-selection algorithm."""

    @abstractmethod
    def select(
        self,
        ranked: Sequence[RankedTrend],
        override_title: str | None = None,
    ) -> SelectedTopic:
        """Choose the best topic, honoring an optional manual override."""
