"""Cloud archive stage (optional).

Runs after upload and mirrors the finished package to object storage. Like the
uploader, it self-gates on ``archive.enabled`` and on credentials actually being
configured. It is best-effort: the video is already on YouTube by this point, so
a backup failure logs a warning and records ``archived=False`` rather than
failing an otherwise successful run.
"""

from __future__ import annotations

import os

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.interfaces import PipelineStage
from ..domain.models import ArchiveResult
from ..providers.archive import S3ArchiveProvider

# Marker dropped in an archived run folder so retention can later distinguish a
# safely-backed-up run from an un-archived one.
ARCHIVED_MARKER = ".archived"


class CloudArchiver(PipelineStage):
    name = "cloud_archive"

    def __init__(self, provider: S3ArchiveProvider) -> None:
        self._provider = provider
        self._logger = get_logger("shorts.archive")

    def is_enabled(self, config) -> bool:
        archive = config.archive
        if not archive.enabled:
            return False
        creds = (
            archive.bucket
            and os.getenv(archive.endpoint_url_env)
            and os.getenv(archive.access_key_id_env)
            and os.getenv(archive.secret_access_key_env)
        )
        if creds:
            return True
        self._logger.warning(
            "archive_skipped_no_credentials",
            hint=(
                f"set archive.bucket and {archive.endpoint_url_env} / "
                f"{archive.access_key_id_env} / {archive.secret_access_key_env} "
                "in .env (see README)"
            ),
        )
        return False

    def run(self, ctx) -> None:
        if ctx.package is None:
            return

        archive = ctx.config.archive
        try:
            with log_duration(self._logger, "cloud_archive"):
                result = self._provider.archive(
                    ctx.package,
                    bucket=archive.bucket,
                    prefix=archive.prefix,
                    include_assets=archive.include_assets,
                )
            (ctx.package.output_dir / ARCHIVED_MARKER).write_text("", encoding="utf-8")
        except Exception as exc:
            # Best-effort: the short is already published; never fail the run.
            self._logger.warning("archive_failed", error=str(exc))
            result = ArchiveResult(archived=False, bucket=archive.bucket)

        ctx.archive_result = result
        ctx.package.archive = result
