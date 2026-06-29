"""Tests for the provider registry / configuration-driven selection."""

from __future__ import annotations

from trend_intelligence.cache.local import LocalFileCache
from trend_intelligence.config.settings import AppConfig, ProviderConfig
from trend_intelligence.domain.models import TrendSource
from trend_intelligence.providers.registry import (
    PROVIDER_CLASSES,
    build_enabled_providers,
    build_providers,
)


def test_builds_all_configured_providers(tmp_path):
    config = AppConfig.load(load_env=False)
    providers = build_providers(config, LocalFileCache(tmp_path))
    sources = {p.source for p in providers}
    assert sources == {
        TrendSource.NEWS_RSS,
        TrendSource.GOOGLE_TRENDS,
        TrendSource.HACKER_NEWS,
        TrendSource.REDDIT,
        TrendSource.YOUTUBE,
    }


def test_enabled_providers_are_credential_free_ones(tmp_path):
    config = AppConfig.load(load_env=False)
    enabled = build_enabled_providers(config, LocalFileCache(tmp_path))
    assert {p.source for p in enabled} == {
        TrendSource.NEWS_RSS,
        TrendSource.GOOGLE_TRENDS,
        TrendSource.HACKER_NEWS,
    }


def test_unknown_provider_is_skipped(tmp_path):
    config = AppConfig.load(load_env=False)
    config.providers["bogus"] = ProviderConfig(enabled=True)
    providers = build_providers(config, LocalFileCache(tmp_path))
    assert len(providers) == len(PROVIDER_CLASSES)  # bogus skipped, known kept


def test_registry_covers_all_classes():
    assert set(PROVIDER_CLASSES) == {
        "news_rss",
        "google_trends",
        "hacker_news",
        "reddit",
        "youtube",
    }
