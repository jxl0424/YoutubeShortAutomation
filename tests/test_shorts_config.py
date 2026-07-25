"""Tests for Stage 2 configuration loading."""

from __future__ import annotations

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.exceptions import ShortsConfigurationError
from shorts.domain.models import VisualType


def test_load_default_config(monkeypatch):
    # The report recipient is env-sourced; unset it so a developer's own
    # REPORT_EMAIL_TO cannot mask the "nothing committed" assertion below.
    monkeypatch.delenv("REPORT_EMAIL_TO", raising=False)
    config = ShortsConfig.load(load_env=False)
    assert config.script.provider == "nvidia_nim"
    assert config.enrichment.enabled is True
    assert (config.script.min_words, config.script.max_words) == (40, 160)
    assert config.voice.provider == "kokoro"
    assert config.voice.voice == "af_heart"
    # Narrator voices rotate per run (mixed genders + US/UK accents).
    assert config.voice.voices == [
        "af_heart",
        "af_bella",
        "am_michael",
        "bf_emma",
        "bm_george",
    ]
    assert config.video.width == 1080
    assert config.video.height == 1920
    assert config.video.scene_text is True
    # Karaoke captions highlight the spoken word in the brand yellow.
    assert config.video.subtitles.highlight_color == "#FFC400"
    # BGM rotates over the tracks in this folder.
    assert config.video.music.dir == "assets/music"
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
    # Email delivery is ON — a report nobody receives is the bug this fixes.
    email = config.report.email
    assert email.enabled is True
    assert (email.smtp_host, email.smtp_port, email.starttls) == (
        "smtp.gmail.com",
        587,
        True,
    )
    assert email.attach_markdown is True
    # This repo is public: no recipient address may ever live in the YAML.
    assert email.to == []


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


def test_report_email_secrets_resolved_from_env(monkeypatch):
    monkeypatch.setenv("REPORT_SMTP_USERNAME", "sender@gmail.com")
    monkeypatch.setenv("REPORT_SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("REPORT_EMAIL_TO", "a@example.com, b@example.com;c@example.com")
    email = ShortsConfig.load(load_env=False).report.email
    assert email.username == "sender@gmail.com"
    assert email.password == "app-password"
    # Comma or semicolon, whitespace tolerated (values get pasted by hand).
    assert email.to == ["a@example.com", "b@example.com", "c@example.com"]


def test_report_email_yaml_recipients_win_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("REPORT_EMAIL_TO", "env@example.com")
    config_path = tmp_path / "shorts.yaml"
    config_path.write_text(
        "report:\n  email:\n    to: [yaml@example.com]\n", encoding="utf-8"
    )
    config = ShortsConfig.load(config_path, load_env=False)
    assert config.report.email.to == ["yaml@example.com"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(ShortsConfigurationError):
        ShortsConfig.load(tmp_path / "nope.yaml", load_env=False)


def test_unknown_key_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("language: en\nmystery: 1\n", encoding="utf-8")
    with pytest.raises(ShortsConfigurationError):
        ShortsConfig.load(bad, load_env=False)
