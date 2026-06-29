"""Tests for the scoring strategy and engine."""

from __future__ import annotations

import pytest

from trend_intelligence.config.settings import ScoringWeights
from trend_intelligence.domain.interfaces import ScoringStrategy
from trend_intelligence.domain.models import (
    AggregatedTrend,
    ScoreBreakdown,
    TrendAnalysis,
    TrendSource,
)
from trend_intelligence.scoring.engine import ScoringEngine
from trend_intelligence.scoring.weighted import WeightedScoringStrategy

WEIGHTS = ScoringWeights().as_mapping()


def _agg(cluster_id="c1", title="Topic", pop=0.5, **kw):
    return AggregatedTrend(
        cluster_id=cluster_id,
        canonical_title=title,
        sources=kw.get("sources", [TrendSource.NEWS_RSS]),
        source_count=kw.get("source_count", 1),
        popularity_score=pop,
        growth_score=kw.get("growth", 0.5),
        engagement_score=kw.get("engagement", 0.5),
    )


def _analysis(cluster_id="c1", **kw):
    return TrendAnalysis(
        cluster_id=cluster_id,
        refined_title=kw.get("title", "Topic"),
        ai_confidence=kw.get("ai_confidence", 0.8),
        visual_potential=kw.get("visual", 0.6),
        educational_value=kw.get("edu", 0.6),
        entertainment_value=kw.get("ent", 0.6),
        estimated_audience_interest=kw.get("interest", 0.7),
    )


def test_breakdown_has_all_factors_and_bounded_total():
    breakdown = WeightedScoringStrategy().score(_agg(), _analysis(), WEIGHTS)
    assert set(breakdown.factors) == set(WEIGHTS)
    assert 0.0 <= breakdown.total <= 1.0


def test_contributions_sum_to_total_when_weights_sum_to_one():
    # default weights sum to 1.0, so weighted contributions sum to the total
    assert sum(WEIGHTS.values()) == pytest.approx(1.0, abs=1e-6)
    breakdown = WeightedScoringStrategy().score(_agg(), _analysis(), WEIGHTS)
    assert sum(breakdown.factors.values()) == pytest.approx(breakdown.total, abs=1e-3)


def test_higher_popularity_scores_higher():
    strat = WeightedScoringStrategy()
    low = strat.score(_agg(pop=0.1), _analysis(), WEIGHTS).total
    high = strat.score(_agg(pop=0.9), _analysis(), WEIGHTS).total
    assert high > low


def test_single_factor_weight_isolates_signal():
    weights = {k: 0.0 for k in WEIGHTS}
    weights["search_popularity"] = 1.0
    breakdown = WeightedScoringStrategy().score(_agg(pop=0.73), _analysis(), weights)
    assert breakdown.total == pytest.approx(0.73, abs=1e-4)


def test_scores_without_analysis():
    breakdown = WeightedScoringStrategy().score(_agg(), None, WEIGHTS)
    assert 0.0 <= breakdown.total <= 1.0


def test_engine_ranks_and_assigns_positions():
    aggregated = [_agg("c1", "Low", pop=0.2), _agg("c2", "High", pop=0.95)]
    analyses = [_analysis("c1"), _analysis("c2")]
    ranked = ScoringEngine(WeightedScoringStrategy(), WEIGHTS).rank(
        aggregated, analyses
    )
    assert [r.rank for r in ranked] == [1, 2]
    assert ranked[0].aggregated_trend.cluster_id == "c2"
    assert ranked[0].final_score >= ranked[1].final_score


def test_engine_drops_trends_without_analysis():
    aggregated = [_agg("c1", "Has analysis"), _agg("c2", "No analysis")]
    analyses = [_analysis("c1")]
    ranked = ScoringEngine(WeightedScoringStrategy(), WEIGHTS).rank(
        aggregated, analyses
    )
    assert len(ranked) == 1
    assert ranked[0].aggregated_trend.cluster_id == "c1"


def test_engine_empty_input():
    assert ScoringEngine(WeightedScoringStrategy(), WEIGHTS).rank([], []) == []


def test_strategy_is_replaceable():
    class ConstantStrategy(ScoringStrategy):
        def score(self, trend, analysis, weights):
            return ScoreBreakdown(factors={"const": 0.42}, total=0.42)

    ranked = ScoringEngine(ConstantStrategy(), WEIGHTS).rank(
        [_agg("c1")], [_analysis("c1")]
    )
    assert ranked[0].final_score == 0.42
