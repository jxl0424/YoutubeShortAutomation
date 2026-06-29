"""Tests for BaseTrendProvider machinery: caching, retries, failure handling."""

from __future__ import annotations

from trend_intelligence.config.settings import HttpConfig, ProviderConfig
from trend_intelligence.domain.exceptions import InvalidResponseError
from trend_intelligence.domain.models import Trend, TrendQuery, TrendSource
from trend_intelligence.providers.base import BaseTrendProvider, RateLimiter

QUERY = TrendQuery(max_trends_per_provider=10)


class DummyProvider(BaseTrendProvider):
    source = TrendSource.CUSTOM

    def __init__(self, *args, raw=None, fail_times=0, exc=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._raw = raw if raw is not None else ["A", "B", "C"]
        self._fail_times = fail_times
        self._exc = exc or ConnectionError("boom")
        self.calls = 0

    def _fetch_raw(self, query):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc
        return self._raw

    def _normalize(self, raw, query):
        return [Trend(title=t, source=self.source, popularity_score=0.5) for t in raw]


def make(cache, *, enabled=True, max_trends=10, max_retries=3, **kw):
    config = ProviderConfig(
        enabled=enabled, max_trends=max_trends, max_retries=max_retries
    )
    http = HttpConfig(backoff_factor=0.0)  # multiplier 0 → no real sleeping
    return DummyProvider(config, cache, http=http, **kw)


def test_discover_success(tmp_path):
    from trend_intelligence.cache.local import LocalFileCache

    provider = make(LocalFileCache(tmp_path))
    result = provider.discover(QUERY)
    assert result.success is True
    assert result.count == 3
    assert {t.title for t in result.trends} == {"A", "B", "C"}


def test_truncates_to_max_trends(tmp_path):
    from trend_intelligence.cache.local import LocalFileCache

    provider = make(LocalFileCache(tmp_path), max_trends=5, raw=list("ABCDEFGHIJ"))
    assert provider.discover(QUERY).count == 5


def test_result_is_cached(tmp_path):
    from trend_intelligence.cache.local import LocalFileCache

    provider = make(LocalFileCache(tmp_path))
    provider.discover(QUERY)
    provider.discover(QUERY)
    assert provider.calls == 1  # second call served from cache


def test_non_retryable_failure_is_graceful(tmp_path):
    from trend_intelligence.cache.local import LocalFileCache

    provider = make(
        LocalFileCache(tmp_path),
        fail_times=99,
        exc=InvalidResponseError("custom", "bad"),
    )
    result = provider.discover(QUERY)
    assert result.success is False
    assert result.error is not None
    assert provider.calls == 1  # not retried


def test_retries_then_succeeds(tmp_path):
    from trend_intelligence.cache.local import LocalFileCache

    provider = make(LocalFileCache(tmp_path), fail_times=2, max_retries=3)
    result = provider.discover(QUERY)
    assert result.success is True
    assert provider.calls == 3  # 2 failures + 1 success


def test_retry_exhausted_returns_failure(tmp_path):
    from trend_intelligence.cache.local import LocalFileCache

    provider = make(LocalFileCache(tmp_path), fail_times=99, max_retries=2)
    result = provider.discover(QUERY)
    assert result.success is False
    assert provider.calls == 3  # 1 initial + 2 retries


def test_disabled_provider_returns_failure(tmp_path):
    from trend_intelligence.cache.local import LocalFileCache

    provider = make(LocalFileCache(tmp_path), enabled=False)
    result = provider.discover(QUERY)
    assert result.success is False
    assert provider.calls == 0


def test_rate_limiter_enforces_interval():
    slept: list[float] = []
    clock = [0.0]
    limiter = RateLimiter(5.0, clock=lambda: clock[0], sleep=lambda s: slept.append(s))
    limiter.acquire()  # first call: no wait
    clock[0] = 2.0
    limiter.acquire()  # 2s elapsed, need 5 → sleep 3
    assert slept == [3.0]


def test_rate_limiter_disabled_when_zero():
    slept: list[float] = []
    limiter = RateLimiter(0.0, clock=lambda: 0.0, sleep=lambda s: slept.append(s))
    limiter.acquire()
    limiter.acquire()
    assert slept == []
