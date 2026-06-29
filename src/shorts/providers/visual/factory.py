"""Builds the configured visual providers, skipping any missing credentials."""

from __future__ import annotations

from trend_intelligence.logging.setup import get_logger

from ...config.settings import AssetsConfig
from ...domain.interfaces import VisualProvider
from .pexels import PexelsVisualProvider
from .pollinations import PollinationsVisualProvider

_logger = get_logger("shorts.visual.factory")


def build_visual_providers(
    config: AssetsConfig,
    *,
    width: int = 1080,
    height: int = 1920,
    timeout: float = 30.0,
) -> list[VisualProvider]:
    providers: list[VisualProvider] = []
    for name in config.providers:
        if name == "pollinations":
            providers.append(
                PollinationsVisualProvider(width=width, height=height, timeout=timeout)
            )
        elif name == "pexels":
            if config.stock.pexels_api_key:
                providers.append(
                    PexelsVisualProvider(
                        api_key=config.stock.pexels_api_key, timeout=timeout
                    )
                )
            else:
                _logger.warning(
                    "visual_provider_skipped",
                    provider="pexels",
                    reason="no PEXELS_API_KEY",
                )
        else:
            _logger.warning("unknown_visual_provider", provider=name)
    return providers
