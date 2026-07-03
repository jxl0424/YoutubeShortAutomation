"""Tests for the PrePublishQA gate."""

from __future__ import annotations

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.exceptions import QAError
from shorts.domain.models import GeneratedShort, RenderedVideo, VideoMetadata
from shorts.pipeline import PipelineContext
from shorts.stages.qa import PrePublishQA


def _passing_ctx(tmp_path):
    """A packaged short that clears every deterministic QA check."""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video-bytes")
    captions = tmp_path / "captions.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    thumb = tmp_path / "thumbnail.png"
    thumb.write_bytes(b"png")

    config = ShortsConfig()
    config.upload.enabled = True
    config.upload.privacy = "public"
    config.upload.qa_fail_privacy = "private"

    ctx = PipelineContext(
        brief=TopicBrief(title="t", category="c", confidence=0.5),
        config=config,
        work_dir=tmp_path,
    )
    ctx.package = GeneratedShort(
        output_dir=tmp_path,
        video_path=video,
        thumbnail_path=thumb,
        captions_path=captions,
    )
    ctx.rendered_video = RenderedVideo(
        path=video, width=1080, height=1920, fps=30, duration_seconds=20.0
    )
    ctx.metadata = VideoMetadata(
        title="A Real Trending Story Today",
        description="Something informative about the topic worth knowing.",
        tags=["news", "tech", "science"],
        hashtags=["#Shorts"],
    )
    return ctx


def test_qa_passes_and_publishes_public(tmp_path):
    ctx = _passing_ctx(tmp_path)
    PrePublishQA().run(ctx)
    assert ctx.qa_report.ok is True
    assert ctx.qa_report.issues == []
    assert ctx.publish_privacy == "public"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda ctx: setattr(ctx.rendered_video, "duration_seconds", 3.0),
        lambda ctx: setattr(ctx.rendered_video, "duration_seconds", 200.0),
        lambda ctx: (
            setattr(ctx.rendered_video, "width", 1920),
            setattr(ctx.rendered_video, "height", 1080),
        ),
        lambda ctx: ctx.package.captions_path.unlink(),
        lambda ctx: setattr(ctx.metadata, "title", "Hi"),
        lambda ctx: setattr(ctx.metadata, "tags", ["only-one"]),
        lambda ctx: ctx.package.thumbnail_path.unlink(),
        lambda ctx: setattr(ctx.metadata, "description", "too short"),
    ],
)
def test_qa_failure_downgrades_to_private(tmp_path, mutate):
    ctx = _passing_ctx(tmp_path)
    mutate(ctx)
    PrePublishQA().run(ctx)  # a failed check never raises
    assert ctx.qa_report.ok is False
    assert ctx.qa_report.issues  # non-empty explanation
    assert ctx.publish_privacy == "private"


def test_qa_enabled_only_when_uploading():
    stage = PrePublishQA()
    config = ShortsConfig()
    config.upload.enabled = False
    assert stage.is_enabled(config) is False
    config.upload.enabled = True
    assert stage.is_enabled(config) is True


def test_qa_requires_rendered_video(tmp_path):
    ctx = _passing_ctx(tmp_path)
    ctx.rendered_video = None
    with pytest.raises(QAError):
        PrePublishQA().run(ctx)
