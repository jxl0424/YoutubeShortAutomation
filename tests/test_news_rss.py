"""Tests for the News RSS provider (feedparser injected as a fake)."""

from __future__ import annotations

import time
from types import SimpleNamespace

from trend_intelligence.cache.local import LocalFileCache
from trend_intelligence.config.settings import HttpConfig, ProviderConfig
from trend_intelligence.domain.models import ContentCategory, TrendQuery, TrendSource
from trend_intelligence.providers.news_rss import NewsRSSProvider

QUERY = TrendQuery(max_trends_per_provider=25)


def _entry(title, link="https://news.example/x", published=None, tags=None):
    entry = {"title": title, "link": link}
    if published is not None:
        entry["published_parsed"] = published
    if tags is not None:
        entry["tags"] = tags
    return entry


def _feed(entries, bozo=0, bozo_exception=None):
    return SimpleNamespace(
        entries=entries, bozo=bozo, bozo_exception=bozo_exception
    )


def make(tmp_path, feeds, parser):
    config = ProviderConfig(enabled=True, max_trends=25, options={"feeds": feeds})
    return NewsRSSProvider(
        config, LocalFileCache(tmp_path), http=HttpConfig(), parser=parser
    )


def test_normalizes_entries(tmp_path):
    feed = _feed([_entry("AI model breaks record"), _entry("Mars rover update")])
    provider = make(tmp_path, ["https://feed"], lambda url: feed)
    result = provider.discover(QUERY)
    assert result.success is True
    assert result.count == 2
    trend = result.trends[0]
    assert trend.source is TrendSource.NEWS_RSS
    assert trend.category is ContentCategory.NEWS
    assert trend.source_url is not None
    assert trend.keywords
    assert 0.0 <= trend.popularity_score <= 1.0


def test_dedups_same_title_across_feeds(tmp_path):
    feeds_map = {
        "f1": _feed([_entry("Breaking story")]),
        "f2": _feed([_entry("Breaking story")]),
    }
    provider = make(tmp_path, ["f1", "f2"], lambda url: feeds_map[url])
    assert provider.discover(QUERY).count == 1


def test_recent_scores_higher_than_old(tmp_path):
    now = time.gmtime(time.time())
    old = time.gmtime(time.time() - 100 * 3600)
    feed = _feed(
        [_entry("Fresh news", published=now), _entry("Stale news", published=old)]
    )
    provider = make(tmp_path, ["https://feed"], lambda url: feed)
    trends = {t.title: t for t in provider.discover(QUERY).trends}
    assert trends["Fresh news"].popularity_score > trends["Stale news"].popularity_score


def test_no_feeds_configured_fails_gracefully(tmp_path):
    provider = make(tmp_path, [], lambda url: _feed([]))
    result = provider.discover(QUERY)
    assert result.success is False


def test_all_feeds_failing_returns_failure(tmp_path):
    def boom(url):
        raise OSError("network down")

    provider = make(tmp_path, ["f1", "f2"], boom)
    result = provider.discover(QUERY)
    assert result.success is False


def test_one_bad_feed_is_skipped(tmp_path):
    good = _feed([_entry("Good story")])

    def parser(url):
        if url == "bad":
            raise OSError("boom")
        return good

    provider = make(tmp_path, ["bad", "good"], parser)
    result = provider.discover(QUERY)
    assert result.success is True
    assert result.count == 1
