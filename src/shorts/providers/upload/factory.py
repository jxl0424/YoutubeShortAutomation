"""Builds the configured upload provider."""

from __future__ import annotations

import os

from ...config.settings import UploadConfig
from ...domain.interfaces import UploadProvider
from .youtube import YouTubeUploadProvider


def build_upload_provider(config: UploadConfig) -> UploadProvider:
    return YouTubeUploadProvider(
        client_secrets_path=os.getenv(config.client_secrets_env),
        token_path=config.token_path,
        privacy=config.privacy,
        category_id=config.category_id,
        contains_synthetic_media=config.contains_synthetic_media,
        made_for_kids=config.made_for_kids,
    )
