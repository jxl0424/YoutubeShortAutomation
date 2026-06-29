"""Tests for the local filesystem cache."""

from __future__ import annotations

import pytest

from trend_intelligence.cache.local import LocalFileCache
from trend_intelligence.domain.exceptions import CacheError


class FakeClock:
    """Controllable clock for deterministic TTL tests."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_set_get_round_trip(tmp_path):
    cache = LocalFileCache(tmp_path)
    cache.set("news_rss", "key1", {"a": 1, "b": [2, 3]})
    assert cache.get("news_rss", "key1") == {"a": 1, "b": [2, 3]}


def test_miss_returns_none(tmp_path):
    cache = LocalFileCache(tmp_path)
    assert cache.get("news_rss", "absent") is None


def test_ttl_expiry(tmp_path):
    clock = FakeClock(1000.0)
    cache = LocalFileCache(tmp_path, clock=clock)
    cache.set("ns", "k", "value", ttl=60)
    assert cache.get("ns", "k") == "value"
    clock.now = 1061.0  # advance past TTL
    assert cache.get("ns", "k") is None


def test_zero_ttl_never_expires(tmp_path):
    clock = FakeClock(1000.0)
    cache = LocalFileCache(tmp_path, clock=clock)
    cache.set("ns", "k", "value", ttl=0)
    clock.now = 10**9
    assert cache.get("ns", "k") == "value"


def test_namespaces_are_isolated(tmp_path):
    cache = LocalFileCache(tmp_path)
    cache.set("a", "k", 1)
    cache.set("b", "k", 2)
    assert cache.get("a", "k") == 1
    assert cache.get("b", "k") == 2


def test_invalidate_key(tmp_path):
    cache = LocalFileCache(tmp_path)
    cache.set("ns", "k", 1)
    cache.invalidate("ns", "k")
    assert cache.get("ns", "k") is None


def test_invalidate_namespace(tmp_path):
    cache = LocalFileCache(tmp_path)
    cache.set("ns", "k1", 1)
    cache.set("ns", "k2", 2)
    cache.invalidate("ns")
    assert cache.get("ns", "k1") is None
    assert cache.get("ns", "k2") is None


def test_disabled_cache_is_noop(tmp_path):
    cache = LocalFileCache(tmp_path, enabled=False)
    cache.set("ns", "k", "value")
    assert cache.get("ns", "k") is None


def test_non_serializable_value_raises(tmp_path):
    cache = LocalFileCache(tmp_path)
    with pytest.raises(CacheError):
        cache.set("ns", "k", {1, 2, 3})  # sets are not JSON-serializable
