"""Tests for thumbnail generation (real Pillow renderer + stage wiring)."""

from __future__ import annotations

from typing import ClassVar

from PIL import Image

from shorts.config.settings import ShortsConfig
from shorts.domain.brief import TopicBrief
from shorts.domain.interfaces import ThumbnailRenderer
from shorts.domain.models import (
    ThumbnailRequest,
    ThumbnailResult,
    VideoMetadata,
    VisualAsset,
    VisualType,
)
from shorts.pipeline import PipelineContext
from shorts.providers.thumbnail.pillow_thumbnail import PillowThumbnailRenderer
from shorts.stages.thumbnail import ThumbnailGenerator

# Small dimensions keep the real render fast.
W, H = 360, 640


def _request(tmp, **kw):
    base = dict(
        output_path=tmp / "thumbnail.png",
        width=W,
        height=H,
        title="This AI Chip Doubles Inference Speed",
    )
    base.update(kw)
    return ThumbnailRequest(**base)


# --- Pillow renderer (real) ------------------------------------------------ #
def test_renders_png_with_solid_background(tmp_path):
    result = PillowThumbnailRenderer().render(_request(tmp_path))
    assert result.path.exists()
    with Image.open(result.path) as img:
        assert img.size == (W, H)
        assert img.format == "PNG"


def test_uses_background_image(tmp_path):
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1080, 1920), (200, 50, 50)).save(bg)
    result = PillowThumbnailRenderer().render(_request(tmp_path, background_path=bg))
    with Image.open(result.path) as img:
        assert img.size == (W, H)


def test_branding_and_long_title_do_not_crash(tmp_path):
    request = _request(
        tmp_path,
        title="A very long thumbnail title that should wrap across several lines nicely",
        branding="@my channel",
    )
    result = PillowThumbnailRenderer().render(request)
    assert result.path.exists()


def test_missing_background_falls_back_to_solid(tmp_path):
    result = PillowThumbnailRenderer().render(
        _request(tmp_path, background_path=tmp_path / "does_not_exist.jpg")
    )
    assert result.path.exists()


def test_video_background_uses_a_real_frame(tmp_path):
    # Stock-video runs pass an mp4 as the background; a mid-clip frame must be
    # used rather than the solid fallback fill.
    import numpy as np
    from moviepy import ImageClip

    video = tmp_path / "scene.mp4"
    red = ImageClip(np.full((112, 64, 3), (200, 30, 30), dtype=np.uint8))
    red.with_duration(0.4).write_videofile(
        str(video), fps=5, codec="libx264", audio=False, logger=None
    )

    result = PillowThumbnailRenderer().render(
        _request(tmp_path, background_path=video, title_overlay=False)
    )
    with Image.open(result.path) as img:
        r, g, b = img.convert("RGB").getpixel((W // 2, 10))
    assert r > 120 and g < 90 and b < 90  # red frame, not the navy fallback


# --- stage ----------------------------------------------------------------- #
class FakeThumbRenderer(ThumbnailRenderer):
    name: ClassVar[str] = "fake"

    def __init__(self):
        self.request = None

    def render(self, request: ThumbnailRequest) -> ThumbnailResult:
        self.request = request
        return ThumbnailResult(
            path=request.output_path, width=request.width, height=request.height
        )


def _ctx(tmp, *, metadata=True, assets=True):
    ctx = PipelineContext(
        brief=TopicBrief(title="Brief Title", category="c", confidence=0.5),
        config=ShortsConfig(),
        work_dir=tmp,
    )
    if metadata:
        ctx.metadata = VideoMetadata(title="Metadata Title", description="d")
    if assets:
        img = tmp / "a0.jpg"
        Image.new("RGB", (1080, 1920), (10, 10, 10)).save(img)
        ctx.assets = [
            VisualAsset(
                scene_index=0,
                visual_type=VisualType.GENERATED_IMAGE,
                path=img,
                source="x",
            )
        ]
    return ctx


def test_stage_builds_request_and_sets_thumbnail(tmp_path):
    renderer = FakeThumbRenderer()
    ctx = _ctx(tmp_path)
    ThumbnailGenerator(renderer).run(ctx)
    assert ctx.thumbnail is not None
    assert renderer.request.title == "Metadata Title"  # prefers metadata title
    assert renderer.request.background_path == tmp_path / "a0.jpg"
    assert renderer.request.output_path == tmp_path / "thumbnail.png"


def test_stage_falls_back_to_brief_title(tmp_path):
    renderer = FakeThumbRenderer()
    ThumbnailGenerator(renderer).run(_ctx(tmp_path, metadata=False))
    assert renderer.request.title == "Brief Title"


def test_stage_is_optional_via_config(tmp_path):
    stage = ThumbnailGenerator(FakeThumbRenderer())
    config = ShortsConfig()
    assert stage.is_enabled(config) is True
    config.thumbnail.enabled = False
    assert stage.is_enabled(config) is False
