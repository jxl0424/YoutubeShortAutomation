"""Tests for the TrendAnalyzer using the deterministic mock LLM."""

from __future__ import annotations

from trend_intelligence.domain.models import (
    AggregatedTrend,
    ContentCategory,
    TrendAnalysis,
    TrendSource,
)
from trend_intelligence.intelligence.analyzer import TrendAnalyzer
from trend_intelligence.intelligence.llm.mock import MockLLMProvider
from trend_intelligence.intelligence.schemas import TrendAnalysisBatch


def _agg(cluster_id, title, **kw):
    return AggregatedTrend(
        cluster_id=cluster_id,
        canonical_title=title,
        sources=[TrendSource.NEWS_RSS],
        source_count=1,
        popularity_score=kw.get("popularity", 0.5),
        categories=kw.get("categories", []),
    )


def test_empty_input_returns_empty():
    assert TrendAnalyzer(MockLLMProvider()).analyze([]) == []


def test_analyzes_each_trend():
    trends = [_agg("c1", "Mars landing"), _agg("c2", "AI chips")]
    analyses = TrendAnalyzer(MockLLMProvider()).analyze(trends)
    assert {a.cluster_id for a in analyses} == {"c1", "c2"}
    assert all(isinstance(a, TrendAnalysis) for a in analyses)
    assert all(a.refined_title for a in analyses)


def test_weak_trends_are_removed():
    trends = [_agg("c1", "Strong topic"), _agg("c2", "Weak topic")]
    mock = MockLLMProvider(keep_filter=lambda t: t["title"] != "Weak topic")
    analyses = TrendAnalyzer(mock).analyze(trends)
    assert {a.cluster_id for a in analyses} == {"c1"}


def test_hallucinated_cluster_ids_are_ignored():
    trends = [_agg("c1", "Real topic")]

    def responder(system, user, schema):
        return schema.model_validate(
            {
                "analyses": [
                    {"cluster_id": "ghost", "keep": True, "refined_title": "Ghost"},
                    {"cluster_id": "c1", "keep": True, "refined_title": "Real"},
                ]
            }
        )

    analyses = TrendAnalyzer(MockLLMProvider(responder=responder)).analyze(trends)
    assert [a.cluster_id for a in analyses] == ["c1"]


def test_duplicate_cluster_ids_collapse():
    trends = [_agg("c1", "Topic")]

    def responder(system, user, schema):
        return schema.model_validate(
            {
                "analyses": [
                    {"cluster_id": "c1", "keep": True, "refined_title": "A"},
                    {"cluster_id": "c1", "keep": True, "refined_title": "B"},
                ]
            }
        )

    analyses = TrendAnalyzer(MockLLMProvider(responder=responder)).analyze(trends)
    assert len(analyses) == 1
    assert analyses[0].refined_title == "A"


def test_retries_then_succeeds():
    trends = [_agg("c1", "Topic")]
    mock = MockLLMProvider(raise_times=1)
    analyses = TrendAnalyzer(mock, max_retries=2).analyze(trends)
    assert len(analyses) == 1
    assert mock.calls == 2


def test_fallback_when_llm_always_fails():
    trends = [
        _agg("c1", "Topic A", popularity=0.8, categories=[ContentCategory.SCIENCE])
    ]
    mock = MockLLMProvider(raise_times=99)
    analyses = TrendAnalyzer(mock, max_retries=1).analyze(trends)
    assert len(analyses) == 1
    fallback = analyses[0]
    assert fallback.cluster_id == "c1"
    assert fallback.keep is True
    assert fallback.ai_confidence == 0.2  # heuristic signature
    assert fallback.estimated_audience_interest == 0.8
    assert fallback.recommended_category is ContentCategory.SCIENCE


def test_mock_returns_batch_type():
    trends = [_agg("c1", "Topic")]
    from trend_intelligence.intelligence.prompts import build_user_prompt

    result = MockLLMProvider().generate_structured(
        system="s", user=build_user_prompt(trends), schema=TrendAnalysisBatch
    )
    assert isinstance(result, TrendAnalysisBatch)
    assert result.analyses[0].cluster_id == "c1"
