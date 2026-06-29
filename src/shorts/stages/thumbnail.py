"""Thumbnail generation stage.

Builds a ``ThumbnailRequest`` (title from metadata, background from the first
scene image) and delegates to the injected ``ThumbnailRenderer``. Optional —
self-gates on ``thumbnail.enabled``.
"""

from __future__ import annotations

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.interfaces import PipelineStage, ThumbnailRenderer
from ..domain.models import ThumbnailRequest, VisualType

_IMAGE_TYPES = {VisualType.GENERATED_IMAGE, VisualType.STOCK_IMAGE}


class ThumbnailGenerator(PipelineStage):
    name = "thumbnail_generation"

    def __init__(self, renderer: ThumbnailRenderer) -> None:
        self._renderer = renderer
        self._logger = get_logger("shorts.thumbnail")

    def is_enabled(self, config) -> bool:
        return config.thumbnail.enabled

    def run(self, ctx) -> None:
        thumb_cfg = ctx.config.thumbnail
        video_cfg = ctx.config.video
        title = ctx.metadata.title if ctx.metadata is not None else ctx.brief.title

        request = ThumbnailRequest(
            output_path=ctx.work_dir / "thumbnail.png",
            width=video_cfg.width,
            height=video_cfg.height,
            title=title,
            background_path=self._background(ctx),
            branding=thumb_cfg.branding,
            title_overlay=thumb_cfg.title_overlay,
        )

        with log_duration(self._logger, "thumbnail_generation"):
            result = self._renderer.render(request)

        ctx.thumbnail = result
        self._logger.info("thumbnail_generated", path=str(result.path))

    @staticmethod
    def _background(ctx):
        for asset in ctx.assets:
            if asset.visual_type in _IMAGE_TYPES and asset.path.exists():
                return asset.path
        return None
