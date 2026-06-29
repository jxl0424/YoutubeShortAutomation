"""Provider registry — builds provider instances from configuration.

Adding a new provider is a two-line change here (import + map entry) plus the
provider class itself. No existing business logic is modified (open/closed).
The rest of the application depends only on the :class:`TrendProvider`
interface, never on these concrete classes.
"""

from __future__ import annotations

from ..cache.base import TrendCache
from ..config.settings import AppConfig
from ..domain.interfaces import TrendProvider
from ..logging.setup import get_logger
from .base import BaseTrendProvider
from .google_trends import GoogleTrendsProvider
from .hacker_news import HackerNewsProvider
from .news_rss import NewsRSSProvider
from .reddit import RedditProvider
from .youtube import YouTubeProvider

_logger = get_logger("providers.registry")

#: Maps a config provider name to its implementation.
PROVIDER_CLASSES: dict[str, type[BaseTrendProvider]] = {
    "news_rss": NewsRSSProvider,
    "google_trends": GoogleTrendsProvider,
    "hacker_news": HackerNewsProvider,
    "reddit": RedditProvider,
    "youtube": YouTubeProvider,
}


def build_providers(config: AppConfig, cache: TrendCache) -> list[TrendProvider]:
    """Instantiate every known, configured provider (enabled or not)."""
    providers: list[TrendProvider] = []
    for name, provider_config in config.providers.items():
        provider_cls = PROVIDER_CLASSES.get(name)
        if provider_cls is None:
            _logger.warning("unknown_provider", provider=name)
            continue
        providers.append(
            provider_cls(
                provider_config,
                cache,
                http=config.http,
                cache_ttl=config.cache.ttl_for(name),
            )
        )
    return providers


def build_enabled_providers(
    config: AppConfig, cache: TrendCache
) -> list[TrendProvider]:
    """Instantiate only providers that are enabled and ready (credentials present)."""
    return [p for p in build_providers(config, cache) if p.is_enabled]
