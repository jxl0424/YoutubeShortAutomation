"""Unit tests for MoviePyRenderer's pure/stub-able paths.

The e2e suite injects a fake renderer, so the quality-critical pieces are covered
here directly: the still-image upscale math and the subtitle-burn finalize step
(bitrate propagation, the no-subtitle move, and the graceful fallback). ffmpeg and
imageio_ffmpeg are stubbed — no real MoviePy render or encode runs.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

from shorts.domain.models import RenderRequest
from shorts.providers.render.moviepy_renderer import MoviePyRenderer


# --- _upscale_sharpen (pure PIL/numpy math) --------------------------------- #
def _image(tmp_path, size):
    from PIL import Image

    path = tmp_path / "img.jpg"
    Image.new("RGB", size, (10, 120, 30)).save(path)
    return path


def test_upscale_sharpen_upscales_small_source_to_frame(tmp_path):
    # Pollinations-sized source (576x1024) must fill 1080x1920 exactly.
    arr = MoviePyRenderer._upscale_sharpen(_image(tmp_path, (576, 1024)), 1080, 1920)
    assert arr.shape == (1920, 1080, 3)


def test_upscale_sharpen_crops_mismatched_aspect(tmp_path):
    # Aspect mismatch: scale to cover, then center-crop to the exact frame.
    arr = MoviePyRenderer._upscale_sharpen(_image(tmp_path, (600, 1024)), 1080, 1920)
    assert arr.shape == (1920, 1080, 3)


def test_upscale_sharpen_downscales_larger_source(tmp_path):
    # 4K-ish source is downscaled (no unsharp needed) but still frame-exact.
    arr = MoviePyRenderer._upscale_sharpen(_image(tmp_path, (2160, 3840)), 1080, 1920)
    assert arr.shape == (1920, 1080, 3)


# --- _finalize (subtitle burn) ----------------------------------------------- #
def _request(tmp_path, **overrides):
    defaults = dict(
        output_path=tmp_path / "video.mp4",
        width=1080,
        height=1920,
        fps=30,
        bitrate="8M",
        audio_path=tmp_path / "narration.mp3",
        subtitle_path=tmp_path / "captions.srt",
        burn_subtitles=True,
    )
    defaults.update(overrides)
    return RenderRequest(**defaults)


def _stub_ffmpeg(monkeypatch, run_fn):
    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        types.SimpleNamespace(get_ffmpeg_exe=lambda: "ffmpeg"),
    )
    monkeypatch.setattr(subprocess, "run", run_fn)


def test_finalize_burn_mirrors_configured_bitrate(tmp_path, monkeypatch):
    raw = tmp_path / "render_raw.mp4"
    raw.write_bytes(b"raw-video")
    (tmp_path / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"burned")

    _stub_ffmpeg(monkeypatch, fake_run)
    request = _request(tmp_path)
    MoviePyRenderer()._finalize(raw, request)

    cmd = captured["cmd"]
    # The re-encode must carry the configured quality target, not ffmpeg defaults.
    assert "-b:v" in cmd and "8M" in cmd
    assert "-c:v" in cmd and "libx264" in cmd
    assert "subtitles=captions.srt" in cmd
    assert not raw.exists()  # raw removed after a successful burn


def test_finalize_without_subtitles_moves_raw_into_place(tmp_path, monkeypatch):
    raw = tmp_path / "render_raw.mp4"
    raw.write_bytes(b"raw-video")

    def unexpected_run(cmd, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("ffmpeg must not run when subtitles are disabled")

    _stub_ffmpeg(monkeypatch, unexpected_run)
    request = _request(tmp_path, burn_subtitles=False)
    MoviePyRenderer()._finalize(raw, request)

    assert request.output_path.read_bytes() == b"raw-video"
    assert not raw.exists()


def test_finalize_burn_failure_falls_back_to_raw_video(tmp_path, monkeypatch):
    raw = tmp_path / "render_raw.mp4"
    raw.write_bytes(b"raw-video")
    (tmp_path / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")

    def failing_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr=b"boom")

    _stub_ffmpeg(monkeypatch, failing_run)
    request = _request(tmp_path)
    MoviePyRenderer()._finalize(raw, request)  # must not raise

    # The un-captioned raw video still ships (soft-sub SRT is packaged anyway).
    assert request.output_path.read_bytes() == b"raw-video"
    assert not raw.exists()
