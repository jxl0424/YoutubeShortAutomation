"""Tests for the Packaging stage + LocalStorageProvider."""

from __future__ import annotations

import json

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.models import (
    RenderedVideo,
    Script,
    ScriptScene,
    ThumbnailResult,
    VideoMetadata,
    VoiceResult,
)
from shorts.pipeline import PipelineContext
from shorts.providers.storage import LocalStorageProvider
from shorts.stages.packaging import Packager


def test_storage_round_trip(tmp_path):
    storage = LocalStorageProvider()
    storage.ensure_dir(tmp_path / "sub")
    p = storage.write_text(tmp_path / "sub" / "a.txt", "hello")
    assert p.read_text(encoding="utf-8") == "hello"
    storage.write_bytes(tmp_path / "b.bin", b"\x00\x01")
    assert storage.exists(tmp_path / "b.bin")
    assert storage.exists(tmp_path / "missing") is False


def _ctx(tmp, *, with_thumbnail=True):
    ctx = PipelineContext(
        brief=TopicBrief(title="AI Chip", category="technology", confidence=0.6),
        config=ShortsConfig(),
        work_dir=tmp,
    )
    ctx.metadata = VideoMetadata(
        title="This AI Chip Doubles Speed",
        description="The chip everyone is talking about.",
        tags=["ai", "chip"],
        hashtags=["#Shorts", "#ai"],
    )
    ctx.script = Script(
        hook="You won't believe this.",
        narration="A short narration about the chip.",
        scenes=[
            ScriptScene(
                index=0,
                narration="intro",
                on_screen_text="AI",
                visual_instruction="show chip",
            )
        ],
        cta="Follow!",
    )
    # media files written by earlier stages
    (tmp / "video.mp4").write_bytes(b"fakevideo")
    (tmp / "captions.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
    )
    ctx.rendered_video = RenderedVideo(
        path=tmp / "video.mp4", width=1080, height=1920, fps=30, duration_seconds=5.0
    )
    ctx.voice = VoiceResult(
        audio_path=tmp / "narration.mp3",
        subtitle_path=tmp / "captions.srt",
        duration_seconds=5.0,
    )
    if with_thumbnail:
        (tmp / "thumbnail.png").write_bytes(b"fakepng")
        ctx.thumbnail = ThumbnailResult(
            path=tmp / "thumbnail.png", width=1080, height=1920
        )
    return ctx


def test_packages_all_artifacts(tmp_path):
    ctx = _ctx(tmp_path)
    Packager(LocalStorageProvider()).run(ctx)
    pkg = ctx.package
    assert pkg is not None
    assert pkg.output_dir == tmp_path

    # text artifacts written
    assert (tmp_path / "metadata.json").exists()
    assert (tmp_path / "description.txt").exists()
    assert (tmp_path / "tags.txt").exists()
    assert (tmp_path / "script.txt").exists()
    assert (tmp_path / "assets").is_dir()
    assert (tmp_path / "logs" / "summary.json").exists()

    # paths recorded on the package
    assert pkg.video_path == tmp_path / "video.mp4"
    assert pkg.thumbnail_path == tmp_path / "thumbnail.png"
    assert pkg.captions_path == tmp_path / "captions.srt"


def test_metadata_json_is_valid(tmp_path):
    ctx = _ctx(tmp_path)
    Packager(LocalStorageProvider()).run(ctx)
    data = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert data["title"] == "This AI Chip Doubles Speed"
    assert data["tags"] == ["ai", "chip"]


def test_tags_and_script_content(tmp_path):
    ctx = _ctx(tmp_path)
    Packager(LocalStorageProvider()).run(ctx)
    assert (tmp_path / "tags.txt").read_text(encoding="utf-8") == "ai, chip"
    script_text = (tmp_path / "script.txt").read_text(encoding="utf-8")
    assert "HOOK" in script_text and "You won't believe this." in script_text
    assert "CTA" in script_text


def test_missing_thumbnail_is_tolerated(tmp_path):
    ctx = _ctx(tmp_path, with_thumbnail=False)
    Packager(LocalStorageProvider()).run(ctx)
    assert ctx.package.thumbnail_path is None
    assert ctx.package.video_path == tmp_path / "video.mp4"


def test_summary_reflects_state(tmp_path):
    ctx = _ctx(tmp_path)
    Packager(LocalStorageProvider()).run(ctx)
    summary = json.loads(
        (tmp_path / "logs" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["metadata_title"] == "This AI Chip Doubles Speed"
    assert summary["duration_seconds"] == 5.0
