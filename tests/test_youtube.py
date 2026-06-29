"""Tests for the YouTube provider (Data API v3; fetch_json injected)."""

from __future__ import annotations

from trend_intelligence.cache.local import LocalFileCache
from trend_intelligence.config.settings import HttpConfig, ProviderConfig
from trend_intelligence.domain.exceptions import ProviderAuthError
from trend_intelligence.domain.models import TrendQuery, TrendSource
from trend_intelligence.providers.youtube import YouTubeProvider

QUERY = TrendQuery(max_trends_per_provider=20)


def _video(vid, title, views, likes=0, comments=0, tags=None):
    return {
        "id": vid,
        "snippet": {"title": title, "channelTitle": "Chan", "tags": tags or []},
        "statistics": {
            "viewCount": str(views),
            "likeCount": str(likes),
            "commentCount": str(comments),
        },
    }


def _fetcher(items, *, error=None, capture=None):
    def fetch(params):
        if capture is not None:
            capture.update(params)
        if error is not None:
            raise error
        return {"items": items}

    return fetch


def make(tmp_path, fetch=None, *, enabled=True, api_key="k", max_trends=20):
    config = ProviderConfig(
        enabled=enabled,
        max_trends=max_trends,
        api_key=api_key,
        api_key_env="YOUTUBE_API_KEY",
        options={"region_code": "US"},
    )
    return YouTubeProvider(
        config,
        LocalFileCache(tmp_path),
        http=HttpConfig(backoff_factor=0.0),
        fetch_json=fetch,
    )


def test_is_enabled_requires_key(tmp_path):
    assert make(tmp_path, api_key=None).is_enabled is False
    assert make(tmp_path, api_key="present").is_enabled is True


def test_normalizes_and_scales_by_views(tmp_path):
    items = [
        _video("v1", "Viral clip", 1_000_000, likes=50_000, comments=8_000),
        _video("v2", "Smaller clip", 100_000, likes=2_000, comments=100),
    ]
    result = make(tmp_path, _fetcher(items)).discover(QUERY)
    assert result.success is True
    assert result.count == 2
    by_title = {t.title: t for t in result.trends}
    assert by_title["Viral clip"].popularity_score == 1.0
    assert by_title["Viral clip"].source is TrendSource.YOUTUBE
    assert by_title["Viral clip"].source_url == "https://www.youtube.com/watch?v=v1"
    assert by_title["Viral clip"].engagement_score == 1.0


def test_request_params_are_correct(tmp_path):
    captured: dict = {}
    make(tmp_path, _fetcher([_video("v1", "X", 10)], capture=captured)).discover(QUERY)
    assert captured["chart"] == "mostPopular"
    assert captured["regionCode"] == "US"
    assert captured["key"] == "k"


def test_empty_response_is_success(tmp_path):
    result = make(tmp_path, _fetcher([])).discover(QUERY)
    assert result.success is True
    assert result.count == 0


def test_auth_error_returns_failure(tmp_path):
    fetch = _fetcher([], error=ProviderAuthError("youtube", "bad key"))
    result = make(tmp_path, fetch).discover(QUERY)
    assert result.success is False
    assert "bad key" in (result.error or "")


def test_truncates_to_max_trends(tmp_path):
    items = [_video(f"v{i}", f"Clip {i}", i * 100) for i in range(1, 30)]
    result = make(tmp_path, _fetcher(items), max_trends=5).discover(QUERY)
    assert result.count == 5
