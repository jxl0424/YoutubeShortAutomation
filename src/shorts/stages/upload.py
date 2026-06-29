"""YouTube upload stage (optional).

Self-gates on ``upload.enabled`` so the pipeline runs fully with uploads off.
When enabled, uploads the packaged video via the injected ``UploadProvider`` and
records the result on both the context and the package.
"""

from __future__ import annotations

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.exceptions import UploadError
from ..domain.interfaces import PipelineStage, UploadProvider


class Uploader(PipelineStage):
    name = "youtube_upload"

    def __init__(self, provider: UploadProvider) -> None:
        self._provider = provider
        self._logger = get_logger("shorts.upload")

    def is_enabled(self, config) -> bool:
        return config.upload.enabled

    def run(self, ctx) -> None:
        if ctx.package is None:
            raise UploadError("upload requires a packaged short")
        if ctx.metadata is None:
            raise UploadError("upload requires metadata")

        with log_duration(self._logger, "youtube_upload"):
            result = self._provider.upload(ctx.package, ctx.metadata)

        ctx.upload_result = result
        ctx.package.upload = result
        self._logger.info("upload_done", video_id=result.video_id, status=result.status)
