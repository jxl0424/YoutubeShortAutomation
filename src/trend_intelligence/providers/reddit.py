"""Reddit provider — scaffolded and disabled until credentials are supplied.

Enabling later requires only: set ``enabled: true`` in config, provide
``REDDIT_CLIENT_ID`` / ``REDDIT_CLIENT_SECRET``, and implement ``_fetch_raw`` /
``_normalize`` (e.g. with ``praw``). No change to the rest of the pipeline.
"""

from __future__ import annotations

import os
from typing import Any

from ..domain.exceptions import ProviderError
from ..domain.models import Trend, TrendQuery, TrendSource
from .base import BaseTrendProvider


class RedditProvider(BaseTrendProvider):
    source = TrendSource.REDDIT

    @property
    def is_enabled(self) -> bool:
        if not self._config.enabled:
            return False
        client_id_env = self._config.options.get("client_id_env", "REDDIT_CLIENT_ID")
        return bool(os.getenv(client_id_env) and self._config.api_key)

    def _fetch_raw(self, query: TrendQuery) -> Any:
        raise ProviderError(
            self.source.value, "Reddit provider is scaffolded but not implemented"
        )

    def _normalize(self, raw: Any, query: TrendQuery) -> list[Trend]:
        return []
