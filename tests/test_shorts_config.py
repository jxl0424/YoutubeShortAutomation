"""Tests for Stage 2 configuration loading."""

from __future__ import annotations

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.exceptions import ShortsConfigurationError
from shorts.domain.models import VisualType


def test_load_default_config():
    config = ShortsConfig.load(load_env=False)
    assert config.script.provider == "nvidia_nim"
    assert config.enrichment.enabled is True
    assert (config.script.min_words, config.script.max_words) == (40, 160)
    assert config.voice.provider == "kokoro"
    assert config.voice.voice == "af_heart"
    assert config.video.width == 1080
    assert config.video.height == 1920
    assert config.video.scene_text is True
    # Shipped config has uploads ON; the Uploader stage still skips itself
    # (with a warning) on machines without OAuth credentials configured.
    assert config.upload.enabled is True
    assert config.visual_planning.default_visual_type is VisualType.STOCK_VIDEO


def test_defaults_without_yaml():
    # All sections have defaults, so the model is usable without a file.
    config = ShortsConfig()
    assert config.video.fps == 30
    assert config.assets.providers == ["pexels", "pollinations"]


def test_secrets_resolved_from_env(monkeypatch):
    # Pin every env var the config reads, so a real key in the developer's
    # environment can never leak into an assertion diff.
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-123")
    monkeypatch.setenv("PEXELS_API_KEY", "pex-456")
    config = ShortsConfig.load(load_env=False)
    assert config.script.api_key == "nv-123"
    assert config.assets.stock.pexels_api_key == "pex-456"


def test_missing_file_raises(tmp_path):
    with pytest.raises(ShortsConfigurationError):
        ShortsConfig.load(tmp_path / "nope.yaml", load_env=False)


def test_unknown_key_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("language: en\nmystery: 1\n", encoding="utf-8")
    with pytest.raises(ShortsConfigurationError):
        ShortsConfig.load(bad, load_env=False)
