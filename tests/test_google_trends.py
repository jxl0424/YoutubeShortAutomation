"""Tests for the Google Trends provider (Trending Now RSS; parser injected)."""

from __future__ import annotations

from types import SimpleNamespace

from trend_intelligence.cache.local import LocalFileCache
from trend_intelligence.config.settings import HttpConfig, ProviderConfig
from trend_intelligence.domain.models import TrendQuery, TrendSource
from trend_intelligence.providers.google_trends import GoogleTrendsProvider

QUERY = TrendQuery(max_trends_per_provider=20)


def _entry(title, traffic="1000+", news_url="https://news.example/a"):
    return {
        "title": title,
        "ht_approx_traffic": traffic,
        "ht_news_item_url": news_url,
        "ht_news_item_title": f"News about {title}",
        "ht_news_item_source": "Example",
        "link": "https://trends.google.com/trending/rss?geo=US",
    }


def _feed(entries, bozo=0):
    return SimpleNamespace(entries=entries, bozo=bozo, bozo_exception=None)


def make(tmp_path, parser, *, max_trends=20, geo="US"):
    config = ProviderConfig(enabled=True, max_trends=max_trends, options={"geo": geo})
    return GoogleTrendsProvider(
        config, LocalFileCache(tmp_path), http=HttpConfig(backoff_factor=0.0), parser=parser
    )


def test_normalizes_and_scales_by_traffic(tmp_path):
    feed = _feed(
        [
            _entry("AI", traffic="5000+"),
            _entry("Bitcoin", traffic="1000+"),
            _entry("Mars", traffic="200+"),
        ]
    )
    provider = make(tmp_path, lambda url: feed)
    result = provider.discover(QUERY)
    assert result.success is True
    assert result.count == 3
    by_title = {t.title: t for t in result.trends}
    assert by_title["AI"].popularity_score == 1.0  # top traffic scaled to 1.0
    assert by_title["AI"].popularity_score > by_title["Mars"].popularity_score
    assert by_title["AI"].source is TrendSource.GOOGLE_TRENDS
    assert by_title["AI"].source_url == "https://news.example/a"


def test_geo_is_used_in_feed_url(tmp_path):
    captured = {}

    def parser(url):
        captured["url"] = url
        return _feed([_entry("X")])

    make(tmp_path, parser, geo="GB").discover(QUERY)
    assert "geo=GB" in captured["url"]


def test_empty_feed_is_success_with_no_trends(tmp_path):
    provider = make(tmp_path, lambda url: _feed([]))
    result = provider.discover(QUERY)
    assert result.success is True
    assert result.count == 0


def test_truncates_to_max_trends(tmp_path):
    feed = _feed([_entry(f"term{i}", traffic=f"{i}00+") for i in range(1, 30)])
    provider = make(tmp_path, lambda url: feed, max_trends=5)
    assert provider.discover(QUERY).count == 5


def test_feed_failure_returns_failure(tmp_path):
    def boom(url):
        raise OSError("network down")

    result = make(tmp_path, boom).discover(QUERY)
    assert result.success is False
