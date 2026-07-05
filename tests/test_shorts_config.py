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
    # Karaoke captions highlight the spoken word in the brand yellow.
    assert config.video.subtitles.highlight_color == "#FFC400"
    # Shipped config has uploads ON; the Uploader stage still skips itself
    # (with a warning) on machines without OAuth credentials configured.
    assert config.upload.enabled is True
    # Auto-publish public on QA pass; a QA failure downgrades to private.
    assert config.upload.privacy == "public"
    assert config.upload.qa_fail_privacy == "private"
    assert config.upload.contains_synthetic_media is True
    assert config.upload.made_for_kids is False
    assert config.visual_planning.default_visual_type is VisualType.STOCK_VIDEO
    # Cloud archive + local retention ship OFF (opt-in; archive needs R2 creds,
    # retention is destructive).
    assert config.archive.enabled is False
    assert config.archive.prefix == "shorts"
    assert config.archive.include_assets is False
    # Retention is ON (prunes old runs' re-downloadable assets/); archive stays
    # off until R2 creds are configured.
    assert config.retention.enabled is True
    assert config.retention.keep_runs == 5
    # Weekly report uses its own read-only token, never the upload token.
    assert config.report.output_dir == "reports"
    assert config.report.top_videos == 5
    assert config.report.token_path == ".secrets/youtube_report_token.json"
    assert config.report.token_path != config.upload.token_path


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
