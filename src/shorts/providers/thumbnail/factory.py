"""Builds the configured thumbnail renderer."""

from __future__ import annotations

from ...config.settings import ThumbnailConfig
from ...domain.exceptions import ShortsConfigurationError
from ...domain.interfaces import ThumbnailRenderer
from .pillow_thumbnail import PillowThumbnailRenderer

_RENDERERS = {"default": PillowThumbnailRenderer, "pillow": PillowThumbnailRenderer}


def build_thumbnail_renderer(config: ThumbnailConfig) -> ThumbnailRenderer:
    renderer_cls = _RENDERERS.get(config.template) or _RENDERERS.get("default")
    if renderer_cls is None:
        raise ShortsConfigurationError(f"unknown thumbnail template: {config.template}")
    return renderer_cls()
