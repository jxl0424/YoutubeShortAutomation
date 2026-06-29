"""Tests for the trend aggregation service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trend_intelligence.aggregation.aggregator import TrendAggregator
from trend_intelligence.domain.models import (
    ContentCategory,
    Trend,
    TrendProviderResult,
    TrendSource,
)


def _trend(title, source=TrendSource.NEWS_RSS, pop=0.5, **kw):
    return Trend(title=title, source=source, popularity_score=pop, **kw)


def _agg(**kw):
    return TrendAggregator(**kw)


def test_empty_input_returns_empty():
    assert _agg().aggregate_trends([]) == []


def test_exact_duplicates_merge_with_source_attribution():
    trends = [
        _trend("Bitcoin hits new high", source=TrendSource.NEWS_RSS, pop=0.6),
        _trend("Bitcoin hits new high", source=TrendSource.GOOGLE_TRENDS, pop=0.5),
    ]
    result = _agg().aggregate_trends(trends)
    assert len(result) == 1
    agg = result[0]
    assert agg.source_count == 2
    assert set(agg.sources) == {TrendSource.NEWS_RSS, TrendSource.GOOGLE_TRENDS}
    assert len(agg.member_trends) == 2


def test_overlapping_titles_cluster_together():
    trends = [
        _trend("Mars rover landing", pop=0.7),
        _trend("Mars rover", pop=0.4),
        _trend("Bitcoin price surge", pop=0.6),
    ]
    result = _agg().aggregate_trends(trends)
    titles = {a.canonical_title for a in result}
    assert len(result) == 2
    assert "Mars rover landing" in titles  # higher-popularity one is canonical
    assert "Bitcoin price surge" in titles


def test_dissimilar_titles_stay_separate():
    trends = [_trend("AI regulation debate"), _trend("Best pasta recipe")]
    assert len(_agg().aggregate_trends(trends)) == 2


def test_canonical_is_highest_popularity_member():
    trends = [
        _trend("Climate summit Paris", pop=0.3),
        _trend("Climate summit Paris 2026", pop=0.9),
    ]
    agg = _agg().aggregate_trends(trends)[0]
    assert agg.canonical_title == "Climate summit Paris 2026"
    assert "Climate summit Paris" in agg.aliases


def test_cross_source_popularity_bonus():
    trends = [
        _trend("Quantum chip breakthrough", source=TrendSource.NEWS_RSS, pop=0.5),
        _trend("Quantum chip breakthrough", source=TrendSource.GOOGLE_TRENDS, pop=0.5),
    ]
    agg = _agg(cross_source_bonus=0.08).aggregate_trends(trends)[0]
    # mean 0.5 + 0.08 * (2 - 1) = 0.58
    assert agg.popularity_score == pytest.approx(0.58, abs=1e-6)


def test_keywords_and_categories_merged():
    trends = [
        _trend(
            "Solar flare alert",
            keywords=["solar", "flare"],
            category=ContentCategory.SCIENCE,
        ),
        _trend(
            "Solar flare alert",
            keywords=["flare", "aurora"],
            category=ContentCategory.NEWS,
        ),
    ]
    agg = _agg().aggregate_trends(trends)[0]
    assert agg.keywords == ["solar", "flare", "aurora"]
    assert set(agg.categories) == {ContentCategory.SCIENCE, ContentCategory.NEWS}


def test_first_and_last_seen_span_members():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    trends = [
        _trend("Eclipse tonight", discovered_at=t0),
        _trend("Eclipse tonight", discovered_at=t0 + timedelta(hours=5)),
    ]
    agg = _agg().aggregate_trends(trends)[0]
    assert agg.first_seen == t0
    assert agg.last_seen == t0 + timedelta(hours=5)


def test_cluster_id_is_deterministic():
    a = _agg().aggregate_trends([_trend("Northern lights")])[0]
    b = _agg().aggregate_trends([_trend("Northern lights")])[0]
    assert a.cluster_id == b.cluster_id


def test_max_aggregated_truncates_strongest_first():
    titles = [
        "Bitcoin rally",
        "Mars mission",
        "Pasta recipe",
        "Quantum computing",
        "Election results",
        "Climate report",
        "Movie premiere",
        "Football final",
    ]
    trends = [_trend(t, pop=i / 10) for i, t in enumerate(titles)]
    result = _agg(max_aggregated=3).aggregate_trends(trends)
    assert len(result) == 3
    scores = [a.popularity_score for a in result]
    assert scores == sorted(scores, reverse=True)


def test_aggregate_skips_failed_provider_results():
    ok = TrendProviderResult(provider=TrendSource.NEWS_RSS, trends=[_trend("X")])
    bad = TrendProviderResult.failure(TrendSource.GOOGLE_TRENDS, "down")
    result = _agg().aggregate([ok, bad])
    assert len(result) == 1
    assert result[0].canonical_title == "X"
