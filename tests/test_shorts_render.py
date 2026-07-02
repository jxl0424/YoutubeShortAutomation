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

from shorts.domain.models import RenderRequest, RenderScene, VisualType
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
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("subtitles=captions.srt:force_style='")
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


def test_force_style_maps_semantic_fields_to_ass(tmp_path):
    request = _request(
        tmp_path,
        subtitle_font="Verdana",
        subtitle_font_size=96,  # 96px at height 1920 -> 14.4 -> 14 ASS units
        subtitle_color="yellow",
        subtitle_position="top",
    )
    style = MoviePyRenderer()._force_style(request)
    assert "FontName=Verdana" in style
    assert "FontSize=14" in style
    assert "PrimaryColour=&H0000FFFF" in style  # yellow RGB -> ASS BGR
    assert "Alignment=8" in style  # top
    assert "Bold=1" in style and "Outline=1.5" in style


def test_force_style_bottom_position_keeps_clear_of_shorts_ui(tmp_path):
    style = MoviePyRenderer()._force_style(_request(tmp_path))
    assert "Alignment=2" in style
    assert "MarginV=50" in style


def test_ass_color_accepts_hex_and_rejects_unknown():
    assert MoviePyRenderer._ass_color("#ff8800") == "&H000088FF"
    assert MoviePyRenderer._ass_color("white") == "&H00FFFFFF"
    assert MoviePyRenderer._ass_color("not-a-color") is None


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


# --- transitions (crossfade) ------------------------------------------------- #
def _scene(seconds):
    return RenderScene(
        asset_path=Path("x.jpg"),
        visual_type=VisualType.GENERATED_IMAGE,
        duration_seconds=seconds,
    )


def test_fade_seconds_zero_when_transitions_off(tmp_path):
    request = _request(tmp_path, transitions=False, scenes=[_scene(3), _scene(3)])
    assert MoviePyRenderer._fade_seconds(request) == 0.0


def test_fade_seconds_zero_for_single_scene(tmp_path):
    request = _request(tmp_path, scenes=[_scene(3)])
    assert MoviePyRenderer._fade_seconds(request) == 0.0


def test_fade_seconds_clamped_to_half_shortest_scene(tmp_path):
    request = _request(tmp_path, scenes=[_scene(3.0), _scene(0.4)])
    assert MoviePyRenderer._fade_seconds(request) == 0.2
    request = _request(tmp_path, scenes=[_scene(3.0), _scene(4.0)])
    assert MoviePyRenderer._fade_seconds(request) == 0.3


def test_crossfade_preserves_scene_start_times_and_total(tmp_path):
    # Real (tiny) MoviePy clips: two 1s scenes + 0.2s fade. The composite must
    # keep the planned timeline (start at 0 and 1, total 2) — narration and
    # caption sync depend on it.
    import numpy as np
    from moviepy import ImageClip

    fade = 0.2
    first = ImageClip(np.full((64, 32, 3), 255, dtype=np.uint8)).with_duration(
        1.0 + fade
    )
    second = ImageClip(np.zeros((64, 32, 3), dtype=np.uint8)).with_duration(1.0)
    request = _request(tmp_path, width=32, height=64, scenes=[_scene(1.0), _scene(1.0)])

    video = MoviePyRenderer()._crossfade([first, second], request, fade)

    assert video.duration == 2.0
    # Mid-crossfade (t=1.1) the black clip is fading in over the white clip:
    # the frame must be a grey blend, proving both clips are visible.
    mid = video.get_frame(1.1).mean()
    assert 40 < mid < 220
    # Well past the fade the second (black) scene fully owns the frame.
    assert video.get_frame(1.8).mean() < 5
    assert video.get_frame(0.5).mean() > 250


# --- scene-text overlays ------------------------------------------------------ #
def _text_scene(seconds, text):
    return RenderScene(
        asset_path=Path("x.jpg"),
        visual_type=VisualType.GENERATED_IMAGE,
        duration_seconds=seconds,
        on_screen_text=text,
    )


def test_text_overlays_timed_per_scene(tmp_path):
    request = _request(
        tmp_path,
        scenes=[
            _text_scene(2.0, "First fact"),
            _text_scene(3.0, None),  # no text -> no overlay
            _text_scene(1.5, "  "),  # blank -> no overlay
            _text_scene(1.5, "Third point"),
        ],
    )
    overlays = MoviePyRenderer()._text_overlays(request)
    assert len(overlays) == 2
    assert [c.start for c in overlays] == [0.0, 6.5]
    assert [c.duration for c in overlays] == [2.0, 1.5]


def test_text_overlay_pixels_appear_in_top_region(tmp_path):
    import numpy as np
    from moviepy import CompositeVideoClip, ImageClip

    w, h = 64, 112
    base = ImageClip(np.zeros((h, w, 3), dtype=np.uint8)).with_duration(1.0)
    request = _request(tmp_path, width=w, height=h, scenes=[_text_scene(1.0, "HI")])

    overlays = MoviePyRenderer()._text_overlays(request)
    video = CompositeVideoClip([base, *overlays], size=(w, h))
    frame = video.get_frame(0.5)

    top, bottom = frame[: h // 2], frame[h // 2 :]
    assert top.max() > 200  # white text (with black stroke) landed up top
    assert bottom.max() < 50  # bottom half untouched
