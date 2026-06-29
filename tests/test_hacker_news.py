"""Tests for the Hacker News provider (Firebase API; fetch_json injected)."""

from __future__ import annotations

from trend_intelligence.cache.local import LocalFileCache
from trend_intelligence.config.settings import HttpConfig, ProviderConfig
from trend_intelligence.domain.models import ContentCategory, TrendQuery, TrendSource
from trend_intelligence.providers.hacker_news import HackerNewsProvider

QUERY = TrendQuery(max_trends_per_provider=20)


def _story(sid, title, score, comments, url=None, type="story"):
    return {
        "id": sid,
        "type": type,
        "title": title,
        "score": score,
        "descendants": comments,
        "url": url,
    }


def _fetcher(ids, items):
    def fetch(url):
        if url.endswith("topstories.json"):
            return ids
        sid = int(url.rsplit("/", 1)[1].split(".")[0])
        return items.get(sid)

    return fetch


def make(tmp_path, fetch, *, max_trends=20):
    config = ProviderConfig(enabled=True, max_trends=max_trends)
    return HackerNewsProvider(
        config,
        LocalFileCache(tmp_path),
        http=HttpConfig(backoff_factor=0.0),
        fetch_json=fetch,
    )


def test_normalizes_stories_by_score_and_comments(tmp_path):
    items = {
        1: _story(1, "Big launch", 500, 300, url="https://a.example"),
        2: _story(2, "Small post", 100, 20),
    }
    provider = make(tmp_path, _fetcher([1, 2], items))
    result = provider.discover(QUERY)
    assert result.success is True
    assert result.count == 2
    by_title = {t.title: t for t in result.trends}
    assert by_title["Big launch"].popularity_score == 1.0  # top score scaled
    assert by_title["Big launch"].source is TrendSource.HACKER_NEWS
    assert by_title["Big launch"].category is ContentCategory.TECHNOLOGY
    assert by_title["Big launch"].source_url == "https://a.example"
    # story without url falls back to the HN item link
    assert "news.ycombinator.com/item?id=2" in by_title["Small post"].source_url


def test_skips_non_story_and_missing_items(tmp_path):
    items = {
        1: _story(1, "A real story", 50, 5),
        2: _story(2, "A job ad", 10, 0, type="job"),
        3: None,  # deleted/missing item
    }
    provider = make(tmp_path, _fetcher([1, 2, 3], items))
    result = provider.discover(QUERY)
    assert result.count == 1
    assert result.trends[0].title == "A real story"


def test_empty_topstories_is_success(tmp_path):
    provider = make(tmp_path, _fetcher([], {}))
    result = provider.discover(QUERY)
    assert result.success is True
    assert result.count == 0


def test_topstories_failure_returns_failure(tmp_path):
    def boom(url):
        raise OSError("network down")

    result = make(tmp_path, boom).discover(QUERY)
    assert result.success is False


def test_truncates_to_max_trends(tmp_path):
    ids = list(range(1, 30))
    items = {i: _story(i, f"Story {i}", i, i) for i in ids}
    provider = make(tmp_path, _fetcher(ids, items), max_trends=5)
    assert provider.discover(QUERY).count == 5
