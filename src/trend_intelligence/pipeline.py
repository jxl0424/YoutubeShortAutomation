"""Composition root for the Trend Intelligence pipeline.

Wires every stage together and runs them in order:

    discovery → aggregation → intelligence → scoring → selection

Providers are fanned out concurrently with a thread pool (their underlying
libraries are blocking). The pipeline depends only on the stage abstractions, so
any provider/strategy/LLM can be swapped via configuration. The single output is
a :class:`SelectedTopic` — the stable contract handed to Stage 2.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

from .aggregation.aggregator import TrendAggregator
from .cache.base import TrendCache
from .cache.local import LocalFileCache
from .config.settings import AppConfig, CacheConfig, LLMConfig
from .domain.exceptions import ConfigurationError
from .domain.interfaces import LLMProvider, TrendProvider
from .domain.models import SelectedTopic, TrendProviderResult, TrendQuery
from .intelligence.analyzer import TrendAnalyzer
from .intelligence.llm.mock import MockLLMProvider
from .intelligence.llm.nvidia_nim import NvidiaNimProvider
from .logging.setup import get_logger, log_duration
from .providers.registry import build_enabled_providers
from .scoring.engine import ScoringEngine
from .scoring.weighted import WeightedScoringStrategy
from .selection.selector import TopicSelector


class TrendIntelligencePipeline:
    """Runs the full discovery-to-selection workflow."""

    def __init__(
        self,
        *,
        providers: Sequence[TrendProvider],
        aggregator: TrendAggregator,
        analyzer: TrendAnalyzer,
        scoring_engine: ScoringEngine,
        selector: TopicSelector,
        max_workers: int = 4,
    ) -> None:
        self._providers = list(providers)
        self._aggregator = aggregator
        self._analyzer = analyzer
        self._scoring = scoring_engine
        self._selector = selector
        self._max_workers = max_workers
        self._logger = get_logger("pipeline")

    def run(
        self,
        query: TrendQuery | None = None,
        *,
        override_title: str | None = None,
    ) -> SelectedTopic:
        query = query or TrendQuery()
        with log_duration(self._logger, "pipeline_run"):
            results = self._discover(query)
            aggregated = self._aggregator.aggregate(results)
            if not aggregated:
                self._logger.warning("pipeline_no_trends")
            analyses = self._analyzer.analyze(aggregated)
            ranked = self._scoring.rank(aggregated, analyses)
            topic = self._selector.select(ranked, override_title=override_title)
        self._logger.info(
            "pipeline_selected", title=topic.title, score=topic.score
        )
        return topic

    def _discover(self, query: TrendQuery) -> list[TrendProviderResult]:
        results: list[TrendProviderResult] = []
        if not self._providers:
            self._logger.warning("no_providers_enabled")
            return results

        with log_duration(self._logger, "discovery"):
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                futures = {
                    executor.submit(p.discover, query): p for p in self._providers
                }
                for future in as_completed(futures):
                    provider = futures[future]
                    try:
                        results.append(future.result())
                    except Exception as exc:  # providers shouldn't raise; defensive
                        self._logger.error(
                            "provider_crashed",
                            provider=provider.source.value,
                            error=str(exc),
                        )
                        results.append(
                            TrendProviderResult.failure(provider.source, str(exc))
                        )

        successful = sum(1 for r in results if r.success)
        discovered = sum(r.count for r in results)
        self._logger.info(
            "discovery_summary",
            providers=len(self._providers),
            successful=successful,
            trends=discovered,
        )
        return results


# --------------------------------------------------------------------------- #
# Composition helpers (the wiring lives here, not in business logic)
# --------------------------------------------------------------------------- #
def build_cache(config: CacheConfig) -> TrendCache:
    # Only the local backend exists today; the interface allows swapping later.
    return LocalFileCache(
        config.directory,
        default_ttl=config.default_ttl_seconds,
        enabled=config.enabled,
    )


def build_llm(config: LLMConfig) -> LLMProvider:
    provider = config.provider.lower()
    if provider == "nvidia_nim":
        return NvidiaNimProvider(config)
    if provider == "mock":
        return MockLLMProvider()
    raise ConfigurationError(f"unknown LLM provider: {config.provider!r}")


def query_from_config(
    config: AppConfig, *, max_trends: int | None = None
) -> TrendQuery:
    return TrendQuery(
        region=config.region,
        language=config.language,
        categories=list(config.categories),
        max_trends_per_provider=max_trends or config.max_trends_per_provider,
    )


def build_pipeline(
    config: AppConfig, *, llm: LLMProvider | None = None
) -> TrendIntelligencePipeline:
    """Build a fully-wired pipeline from configuration."""
    cache = build_cache(config.cache)
    providers = build_enabled_providers(config, cache)
    aggregator = TrendAggregator(
        similarity_threshold=config.aggregation.similarity_threshold,
        cross_source_bonus=config.aggregation.cross_source_bonus,
        max_aggregated=config.aggregation.max_aggregated,
        min_token_length=config.aggregation.min_token_length,
    )
    analyzer = TrendAnalyzer(
        llm or build_llm(config.llm), max_retries=config.llm.max_retries
    )
    scoring = ScoringEngine(WeightedScoringStrategy(), config.scoring.as_mapping())
    selector = TopicSelector(config.selection)
    return TrendIntelligencePipeline(
        providers=providers,
        aggregator=aggregator,
        analyzer=analyzer,
        scoring_engine=scoring,
        selector=selector,
    )
