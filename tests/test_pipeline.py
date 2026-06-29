"""End-to-end pipeline tests with fake providers and the mock LLM (no network)."""

from __future__ import annotations

import pytest

from trend_intelligence.aggregation.aggregator import TrendAggregator
from trend_intelligence.config.settings import (
    AppConfig,
    LLMConfig,
    ScoringWeights,
    SelectionConfig,
)
from trend_intelligence.domain.exceptions import ConfigurationError, SelectionError
from trend_intelligence.domain.interfaces import TrendProvider
from trend_intelligence.domain.models import (
    SelectedTopic,
    Trend,
    TrendProviderResult,
    TrendQuery,
    TrendSource,
)
from trend_intelligence.intelligence.analyzer import TrendAnalyzer
from trend_intelligence.intelligence.llm.mock import MockLLMProvider
from trend_intelligence.intelligence.llm.nvidia_nim import NvidiaNimProvider
from trend_intelligence.pipeline import (
    TrendIntelligencePipeline,
    build_llm,
    build_pipeline,
    query_from_config,
)
from trend_intelligence.scoring.engine import ScoringEngine
from trend_intelligence.scoring.weighted import WeightedScoringStrategy
from trend_intelligence.selection.selector import TopicSelector


class FakeProvider(TrendProvider):
    def __init__(self, source, trends=None, *, crash=False):
        self._source = source
        self._trends = trends or []
        self._crash = crash

    @property
    def source(self):
        return self._source

    @property
    def is_enabled(self):
        return True

    def discover(self, query):
        if self._crash:
            raise RuntimeError("provider exploded")
        return TrendProviderResult(provider=self._source, trends=self._trends)


def _trend(title, source=TrendSource.NEWS_RSS, pop=0.5):
    return Trend(title=title, source=source, popularity_score=pop, growth_score=0.5)


def _pipeline(providers):
    return TrendIntelligencePipeline(
        providers=providers,
        aggregator=TrendAggregator(),
        analyzer=TrendAnalyzer(MockLLMProvider()),
        scoring_engine=ScoringEngine(
            WeightedScoringStrategy(), ScoringWeights().as_mapping()
        ),
        selector=TopicSelector(SelectionConfig()),
    )


def test_run_end_to_end_returns_selected_topic():
    providers = [
        FakeProvider(TrendSource.NEWS_RSS, [_trend("Mars rover landing", pop=0.8)]),
        FakeProvider(
            TrendSource.GOOGLE_TRENDS,
            [_trend("Bitcoin surge", TrendSource.GOOGLE_TRENDS, 0.4)],
        ),
    ]
    topic = _pipeline(providers).run(TrendQuery())
    assert isinstance(topic, SelectedTopic)
    assert topic.title
    assert 0.0 <= topic.score <= 1.0
    assert topic.ranked_trend.analysis is not None
    assert topic.ranked_trend.aggregated_trend.canonical_title == "Mars rover landing"


def test_cross_source_merge_in_pipeline():
    providers = [
        FakeProvider(TrendSource.NEWS_RSS, [_trend("AI breakthrough", pop=0.6)]),
        FakeProvider(
            TrendSource.GOOGLE_TRENDS,
            [_trend("AI breakthrough", TrendSource.GOOGLE_TRENDS, 0.9)],
        ),
    ]
    topic = _pipeline(providers).run(TrendQuery())
    assert topic.ranked_trend.aggregated_trend.source_count == 2


def test_provider_crash_is_tolerated():
    providers = [
        FakeProvider(TrendSource.GOOGLE_TRENDS, crash=True),
        FakeProvider(TrendSource.NEWS_RSS, [_trend("Survivor topic", pop=0.7)]),
    ]
    topic = _pipeline(providers).run(TrendQuery())
    assert topic.ranked_trend.aggregated_trend.canonical_title == "Survivor topic"


def test_empty_discovery_raises_selection_error():
    providers = [FakeProvider(TrendSource.NEWS_RSS, [])]
    with pytest.raises(SelectionError):
        _pipeline(providers).run(TrendQuery())


def test_manual_override_end_to_end():
    providers = [
        FakeProvider(
            TrendSource.NEWS_RSS,
            [_trend("Popular topic", pop=0.9), _trend("Niche topic", pop=0.2)],
        )
    ]
    topic = _pipeline(providers).run(TrendQuery(), override_title="Niche topic")
    assert topic.manual_override is True
    assert topic.title == "Niche topic"


def test_build_pipeline_from_config_wires_enabled_providers():
    config = AppConfig.load(load_env=False)
    config.llm.provider = "mock"
    pipeline = build_pipeline(config)
    sources = {p.source for p in pipeline._providers}
    assert sources == {
        TrendSource.NEWS_RSS,
        TrendSource.GOOGLE_TRENDS,
        TrendSource.HACKER_NEWS,
    }


def test_build_llm_factory():
    assert isinstance(build_llm(LLMConfig(provider="mock")), MockLLMProvider)
    assert isinstance(
        build_llm(LLMConfig(provider="nvidia_nim", api_key="k")), NvidiaNimProvider
    )
    with pytest.raises(ConfigurationError):
        build_llm(LLMConfig(provider="does_not_exist"))


def test_query_from_config():
    config = AppConfig.load(load_env=False)
    query = query_from_config(config, max_trends=7)
    assert query.region == config.region
    assert query.max_trends_per_provider == 7
