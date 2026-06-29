"""Upload providers for Stage 2."""

from .factory import build_upload_provider
from .youtube import YouTubeUploadProvider

__all__ = ["build_upload_provider", "YouTubeUploadProvider"]
