"""Builds the configured archive provider (credentials resolved from env)."""

from __future__ import annotations

import os

from ...config.settings import ArchiveConfig
from .s3 import S3ArchiveProvider


def build_archive_provider(config: ArchiveConfig) -> S3ArchiveProvider:
    return S3ArchiveProvider(
        endpoint_url=os.getenv(config.endpoint_url_env),
        access_key_id=os.getenv(config.access_key_id_env),
        secret_access_key=os.getenv(config.secret_access_key_env),
    )
