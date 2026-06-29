"""Tests for configuration loading."""

from __future__ import annotations

import pytest

from trend_intelligence.config.settings import AppConfig
from trend_intelligence.domain.exceptions import ConfigurationError


def test_load_default_config():
    """The shipped config/default.yaml loads and parses as expected."""
    config = AppConfig.load(load_env=False)
    assert config.region == "US"
    assert config.llm.provider == "nvidia_nim"
    assert config.providers["news_rss"].enabled is True
    assert config.providers["reddit"].enabled is False
    # config-enabled providers (the `enabled:` flag). youtube is enabled here but
    # only *activates* once its API key is present (see registry tests).
    assert set(config.enabled_providers()) == {
        "news_rss",
        "google_trends",
        "hacker_news",
        "youtube",
    }
    assert config.providers["news_rss"].options["feeds"]


def test_scoring_weights_sum_to_one():
    config = AppConfig.load(load_env=False)
    assert sum(config.scoring.as_mapping().values()) == pytest.approx(1.0, abs=1e-6)


def test_cache_ttl_override():
    config = AppConfig.load(load_env=False)
    assert config.cache.ttl_for("aggregated") == 1800
    assert config.cache.ttl_for("news_rss") == config.cache.default_ttl_seconds


def test_llm_api_key_resolved_from_env(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "secret-123")
    config = AppConfig.load(load_env=False)
    assert config.llm.api_key == "secret-123"


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigurationError):
        AppConfig.load(tmp_path / "does_not_exist.yaml", load_env=False)


def test_unknown_top_level_key_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("region: US\nmystery_key: 1\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        AppConfig.load(bad, load_env=False)


def test_invalid_yaml_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("region: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        AppConfig.load(bad, load_env=False)
