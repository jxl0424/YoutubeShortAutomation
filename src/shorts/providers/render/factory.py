"""Builds the configured video renderer."""

from __future__ import annotations

from ...config.settings import VideoConfig
from ...domain.exceptions import ShortsConfigurationError
from ...domain.interfaces import VideoRenderer
from .moviepy_renderer import MoviePyRenderer

_RENDERERS = {"moviepy": MoviePyRenderer, "default": MoviePyRenderer}


def build_renderer(config: VideoConfig) -> VideoRenderer:
    renderer_cls = _RENDERERS.get(config.template) or _RENDERERS.get("default")
    if renderer_cls is None:
        raise ShortsConfigurationError(f"unknown video template: {config.template}")
    return renderer_cls()
