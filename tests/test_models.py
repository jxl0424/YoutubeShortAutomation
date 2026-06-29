"""Tests for the domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from trend_intelligence.domain.models import (
    ContentCategory,
    Trend,
    TrendProviderResult,
    TrendSource,
)


def _trend(**overrides) -> Trend:
    base = dict(title="AI breakthrough", source=TrendSource.NEWS_RSS)
    base.update(overrides)
    return Trend(**base)


def test_trend_defaults_and_category():
    trend = _trend()
    assert trend.category is ContentCategory.OTHER
    assert trend.popularity_score == 0.0
    assert trend.confidence == 0.5
    assert trend.discovered_at.tzinfo is not None  # timezone-aware


def test_trend_title_is_stripped():
    assert _trend(title="  Spaced out  ").title == "Spaced out"


def test_trend_empty_title_rejected():
    with pytest.raises(ValidationError):
        _trend(title="   ")


@pytest.mark.parametrize("score", [-0.1, 1.1])
def test_trend_score_bounds_enforced(score):
    with pytest.raises(ValidationError):
        _trend(popularity_score=score)


def test_unknown_field_forbidden():
    with pytest.raises(ValidationError):
        _trend(bogus_field=123)


def test_trend_json_round_trip():
    trend = _trend(keywords=["ai", "ml"], popularity_score=0.8)
    restored = Trend.model_validate_json(trend.model_dump_json())
    assert restored == trend


def test_provider_result_count_and_success():
    result = TrendProviderResult(
        provider=TrendSource.NEWS_RSS, trends=[_trend(), _trend(title="Second")]
    )
    assert result.count == 2
    assert result.success is True


def test_provider_result_failure_factory():
    result = TrendProviderResult.failure(
        TrendSource.GOOGLE_TRENDS, "timeout", execution_time_ms=12.5
    )
    assert result.success is False
    assert result.error == "timeout"
    assert result.count == 0
    assert result.execution_time_ms == 12.5
