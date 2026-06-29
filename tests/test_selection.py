"""Tests for the topic selector."""

from __future__ import annotations

import pytest

from trend_intelligence.config.settings import SelectionConfig
from trend_intelligence.domain.exceptions import SelectionError
from trend_intelligence.domain.models import (
    AggregatedTrend,
    RankedTrend,
    SafetyFlag,
    ScoreBreakdown,
    TrendAnalysis,
    TrendSource,
)
from trend_intelligence.selection.selector import TopicSelector


def _ranked(cid, title, score, *, is_safe=True, flags=None, edu=0.5, refined=None):
    agg = AggregatedTrend(
        cluster_id=cid,
        canonical_title=title,
        sources=[TrendSource.NEWS_RSS],
        source_count=1,
        popularity_score=score,
    )
    analysis = TrendAnalysis(
        cluster_id=cid,
        refined_title=refined or title,
        is_safe=is_safe,
        safety_flags=flags or [],
        educational_value=edu,
    )
    return RankedTrend(
        aggregated_trend=agg,
        analysis=analysis,
        score_breakdown=ScoreBreakdown(total=score),
        final_score=score,
    )


def test_empty_raises():
    with pytest.raises(SelectionError):
        TopicSelector().select([])


def test_selects_highest_score():
    ranked = [_ranked("a", "Low", 0.5), _ranked("b", "High", 0.9), _ranked("c", "Mid", 0.3)]
    topic = TopicSelector().select(ranked)
    assert topic.ranked_trend.aggregated_trend.cluster_id == "b"
    assert topic.manual_override is False
    assert topic.score == 0.9


def test_alternatives_are_populated_and_capped():
    ranked = [_ranked(str(i), f"T{i}", i / 10) for i in range(8)]
    topic = TopicSelector(SelectionConfig(max_alternatives=3)).select(ranked)
    assert len(topic.alternatives) == 3
    # alternatives are the next-best, descending
    alt_scores = [a.final_score for a in topic.alternatives]
    assert alt_scores == sorted(alt_scores, reverse=True)
    assert topic.score >= alt_scores[0]


def test_min_score_filters_out_low():
    ranked = [_ranked("a", "Low", 0.1)]
    with pytest.raises(SelectionError):
        TopicSelector(SelectionConfig(min_score=0.5)).select(ranked)


def test_unsafe_topic_is_skipped():
    ranked = [
        _ranked("a", "Top but unsafe", 0.95, is_safe=False),
        _ranked("b", "Safe runner-up", 0.6),
    ]
    topic = TopicSelector().select(ranked)
    assert topic.ranked_trend.aggregated_trend.cluster_id == "b"


def test_misinformation_flag_disqualifies():
    ranked = [
        _ranked("a", "Top", 0.95, flags=[SafetyFlag.MISINFORMATION]),
        _ranked("b", "Safe", 0.6),
    ]
    topic = TopicSelector().select(ranked)
    assert topic.ranked_trend.aggregated_trend.cluster_id == "b"


def test_all_unsafe_raises():
    ranked = [_ranked("a", "Bad", 0.9, is_safe=False)]
    with pytest.raises(SelectionError):
        TopicSelector().select(ranked)


def test_safety_filter_can_be_disabled():
    ranked = [_ranked("a", "Unsafe top", 0.9, is_safe=False)]
    config = SelectionConfig(require_monetization_safe=False)
    topic = TopicSelector(config).select(ranked)
    assert topic.ranked_trend.aggregated_trend.cluster_id == "a"


def test_manual_override_wins_even_if_lower():
    ranked = [_ranked("a", "Popular thing", 0.9), _ranked("b", "Niche thing", 0.2)]
    topic = TopicSelector().select(ranked, override_title="Niche thing")
    assert topic.manual_override is True
    assert topic.ranked_trend.aggregated_trend.cluster_id == "b"
    assert "Niche thing" in topic.selection_reason


def test_override_not_found_raises():
    ranked = [_ranked("a", "Real topic", 0.9)]
    with pytest.raises(SelectionError):
        TopicSelector().select(ranked, override_title="Does not exist")


def test_evergreen_bonus_changes_winner():
    ranked = [
        _ranked("a", "Trending", 0.80, edu=0.1),
        _ranked("b", "Evergreen", 0.75, edu=0.9),
    ]
    config = SelectionConfig(evergreen_bonus=0.1)
    topic = TopicSelector(config).select(ranked)
    # 0.75 + 0.1*0.9 = 0.84 beats 0.80 + 0.1*0.1 = 0.81
    assert topic.ranked_trend.aggregated_trend.cluster_id == "b"


def test_title_uses_refined_title():
    ranked = [_ranked("a", "raw title", 0.9, refined="Punchy Refined Title")]
    topic = TopicSelector().select(ranked)
    assert topic.title == "Punchy Refined Title"
