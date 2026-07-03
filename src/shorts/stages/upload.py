"""YouTube upload stage (optional).

Self-gates on ``upload.enabled`` — and, when enabled, on OAuth credentials
actually being configured — so the pipeline runs fully out of the box even with
uploads switched on in the shipped config. When active, uploads the packaged
video via the injected ``UploadProvider`` and records the result on both the
context and the package.
"""

from __future__ import annotations

import os
from pathlib import Path

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.exceptions import UploadError
from ..domain.interfaces import PipelineStage, UploadProvider


class Uploader(PipelineStage):
    name = "youtube_upload"

    def __init__(self, provider: UploadProvider) -> None:
        self._provider = provider
        self._logger = get_logger("shorts.upload")

    def is_enabled(self, config) -> bool:
        upload = config.upload
        if not upload.enabled:
            return False
        # A client-secrets path in the env or an already-cached OAuth token
        # means uploads can work; with neither, skip instead of failing the
        # final stage of an otherwise successful run.
        if os.getenv(upload.client_secrets_env) or Path(upload.token_path).exists():
            return True
        self._logger.warning(
            "upload_skipped_no_credentials",
            hint=(
                f"set {upload.client_secrets_env} in .env (see README) "
                f"or provide {upload.token_path}"
            ),
        )
        return False

    def run(self, ctx) -> None:
        if ctx.package is None:
            raise UploadError("upload requires a packaged short")
        if ctx.metadata is None:
            raise UploadError("upload requires metadata")

        # PrePublishQA resolves this (public on pass, review privacy on fail);
        # fall back to the configured privacy if the QA stage was skipped.
        privacy = ctx.publish_privacy or ctx.config.upload.privacy
        with log_duration(self._logger, "youtube_upload"):
            result = self._provider.upload(ctx.package, ctx.metadata, privacy=privacy)

        ctx.upload_result = result
        ctx.package.upload = result
        self._logger.info(
            "upload_done",
            video_id=result.video_id,
            status=result.status,
            privacy=privacy,
        )
