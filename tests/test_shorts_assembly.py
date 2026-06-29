"""Tests for the Video Assembly stage (renderer injected as a fake)."""

from __future__ import annotations

from typing import ClassVar

import pytest

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.exceptions import RenderError
from shorts.domain.interfaces import VideoRenderer
from shorts.domain.models import (
    RenderedVideo,
    RenderRequest,
    Scene,
    ScenePlan,
    VisualAsset,
    VisualType,
    VoiceResult,
)
from shorts.pipeline import PipelineContext
from shorts.stages.assembly import VideoAssembler


class FakeRenderer(VideoRenderer):
    name: ClassVar[str] = "fake"

    def __init__(self):
        self.request: RenderRequest | None = None

    def render(self, request: RenderRequest) -> RenderedVideo:
        self.request = request
        return RenderedVideo(
            path=request.output_path,
            width=request.width,
            height=request.height,
            fps=request.fps,
            duration_seconds=5.0,
            bitrate=request.bitrate,
        )


def _ctx(tmp, *, with_voice=True, with_assets=True, with_plan=True):
    ctx = PipelineContext(
        brief=TopicBrief(title="t", category="c", confidence=0.5),
        config=ShortsConfig(),
        work_dir=tmp,
    )
    if with_plan:
        ctx.scene_plan = ScenePlan(
            scenes=[
                Scene(
                    index=0,
                    narration="n0",
                    duration_seconds=3.0,
                    visual_type=VisualType.GENERATED_IMAGE,
                    visual_query="q",
                    on_screen_text="A",
                ),
                Scene(
                    index=1,
                    narration="n1",
                    duration_seconds=2.0,
                    visual_type=VisualType.STOCK_VIDEO,
                    visual_query="q",
                ),
            ]
        )
    if with_assets:
        ctx.assets = [
            VisualAsset(
                scene_index=0,
                visual_type=VisualType.GENERATED_IMAGE,
                path=tmp / "a0.jpg",
                source="x",
            ),
            VisualAsset(
                scene_index=1,
                visual_type=VisualType.STOCK_VIDEO,
                path=tmp / "a1.mp4",
                source="y",
            ),
        ]
    if with_voice:
        ctx.voice = VoiceResult(
            audio_path=tmp / "narration.mp3",
            subtitle_path=tmp / "captions.srt",
            duration_seconds=5.0,
        )
    return ctx


def test_builds_request_and_sets_rendered_video(tmp_path):
    renderer = FakeRenderer()
    ctx = _ctx(tmp_path)
    VideoAssembler(renderer).run(ctx)

    assert ctx.rendered_video is not None
    assert ctx.rendered_video.path == tmp_path / "video.mp4"
    req = renderer.request
    assert req.width == 1080 and req.height == 1920 and req.fps == 30
    assert len(req.scenes) == 2
    assert req.scenes[0].asset_path == tmp_path / "a0.jpg"
    assert req.scenes[1].visual_type is VisualType.STOCK_VIDEO
    assert req.audio_path == tmp_path / "narration.mp3"
    assert req.subtitle_path == tmp_path / "captions.srt"


def test_requires_voice(tmp_path):
    with pytest.raises(RenderError):
        VideoAssembler(FakeRenderer()).run(_ctx(tmp_path, with_voice=False))


def test_requires_assets(tmp_path):
    with pytest.raises(RenderError):
        VideoAssembler(FakeRenderer()).run(_ctx(tmp_path, with_assets=False))


def test_requires_scene_plan(tmp_path):
    with pytest.raises(RenderError):
        VideoAssembler(FakeRenderer()).run(_ctx(tmp_path, with_plan=False))


def test_missing_asset_for_scene_raises(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.assets = [ctx.assets[0]]  # drop the asset for scene 1
    with pytest.raises(RenderError):
        VideoAssembler(FakeRenderer()).run(ctx)


def test_music_wired_when_enabled(tmp_path):
    renderer = FakeRenderer()
    ctx = _ctx(tmp_path)
    ctx.config.video.music.enabled = True
    ctx.config.video.music.path = str(tmp_path / "bg.mp3")
    VideoAssembler(renderer).run(ctx)
    assert renderer.request.music_path == tmp_path / "bg.mp3"
