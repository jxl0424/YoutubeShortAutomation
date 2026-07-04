"""S3-compatible archive provider.

Mirrors a finished package to object storage (Cloudflare R2 by default, but any
S3 API works — B2, AWS S3, MinIO — by changing the endpoint and keys). boto3 is
lazy-imported via the optional ``cloud`` extra; the client is injectable so
tests never touch the network.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, ClassVar

from trend_intelligence.logging.setup import get_logger

from ...domain.exceptions import ArchiveError
from ...domain.models import ArchiveResult, GeneratedShort


class S3ArchiveProvider:
    name: ClassVar[str] = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._client = client
        self._logger = get_logger("shorts.archive")

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise ArchiveError(
                "install the 'cloud' extra for archive support: pip install -e '.[cloud]'"
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
        )
        return self._client

    def archive(
        self,
        package: GeneratedShort,
        *,
        bucket: str,
        prefix: str = "shorts",
        include_assets: bool = False,
    ) -> ArchiveResult:
        """Upload the package's deliverable artifacts under ``prefix/run_name/``.

        The raw ``assets/`` footage is skipped unless ``include_assets`` — it is
        large and re-downloadable from the stock provider.
        """
        run_name = package.output_dir.name
        files = self._collect_files(package, include_assets)
        if not files:
            raise ArchiveError("no artifacts to archive")

        client = self._get_client()
        keys: list[str] = []
        for path in files:
            rel = path.relative_to(package.output_dir).as_posix()
            key = f"{prefix}/{run_name}/{rel}" if prefix else f"{run_name}/{rel}"
            content_type = (
                mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )
            with path.open("rb") as handle:
                client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=handle,
                    ContentType=content_type,
                )
            keys.append(key)

        self._logger.info("archived", bucket=bucket, count=len(keys), run=run_name)
        return ArchiveResult(archived=True, bucket=bucket, keys=keys)

    def _collect_files(
        self, package: GeneratedShort, include_assets: bool
    ) -> list[Path]:
        candidates = [
            package.video_path,
            package.thumbnail_path,
            package.captions_path,
            package.metadata_path,
            package.description_path,
            package.tags_path,
            package.script_path,
        ]
        files = [p for p in candidates if p is not None and Path(p).exists()]
        if package.logs_dir is not None:
            summary = Path(package.logs_dir) / "summary.json"
            if summary.exists():
                files.append(summary)
        if include_assets and package.assets_dir is not None:
            assets = Path(package.assets_dir)
            if assets.is_dir():
                files.extend(sorted(p for p in assets.iterdir() if p.is_file()))
        return files
