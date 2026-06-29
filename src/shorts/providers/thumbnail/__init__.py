"""Thumbnail renderers for Stage 2."""

from .factory import build_thumbnail_renderer
from .pillow_thumbnail import PillowThumbnailRenderer

__all__ = ["build_thumbnail_renderer", "PillowThumbnailRenderer"]
