"""News RSS provider — discovers trends from configured RSS/Atom feeds.

Credential-free. Aggregates entries across all configured feeds; a single bad
feed is logged and skipped. Popularity is approximated from recency (RSS has no
native popularity signal); the LLM stage refines category/quality later.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import feedparser

from ..domain.exceptions import InvalidResponseError
from ..domain.models import ContentCategory, Trend, TrendQuery, TrendSource
from .base import BaseTrendProvider, extract_keywords

_FRESHNESS_WINDOW_HOURS = 48.0


def _entry_get(entry: Any, key: str, default: Any = None) -> Any:
    """Read a field from a feedparser entry (dict- or attribute-style)."""
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _freshness(published_parsed: Any) -> float:
    """Map a published time.struct_time/tuple to a 0-1 recency score."""
    if not published_parsed:
        return 0.4  # unknown publish time → mild signal
    try:
        published = datetime(*published_parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 0.4
    age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    return max(0.0, min(1.0, 1.0 - age_hours / _FRESHNESS_WINDOW_HOURS))


class NewsRSSProvider(BaseTrendProvider):
    source = TrendSource.NEWS_RSS

    def __init__(
        self,
        *args: Any,
        parser: Callable[[str], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._parser = parser or feedparser.parse

    def _fetch_raw(self, query: TrendQuery) -> list[dict[str, Any]]:
        feeds = self._config.options.get("feeds", [])
        if not feeds:
            raise InvalidResponseError(self.source.value, "no feeds configured")

        raw_entries: list[dict[str, Any]] = []
        failures = 0
        for url in feeds:
            try:
                parsed = self._parser(url)
            except Exception as exc:  # one feed failing must not kill the run
                self._logger.warning("rss_feed_error", feed=url, error=str(exc))
                failures += 1
                continue
            entries = getattr(parsed, "entries", None) or []
            if getattr(parsed, "bozo", 0) and not entries:
                self._logger.warning(
                    "rss_feed_bozo",
                    feed=url,
                    error=str(getattr(parsed, "bozo_exception", "")),
                )
                failures += 1
                continue
            for entry in entries:
                raw_entries.append({"entry": entry, "feed": url})

        if not raw_entries and failures:
            # Every feed failed — treat as transient so retries can recover.
            raise ConnectionError(f"all {failures} RSS feed(s) failed")
        return raw_entries

    def _normalize(
        self, raw: list[dict[str, Any]], query: TrendQuery
    ) -> list[Trend]:
        trends: list[Trend] = []
        for item in raw:
            entry, feed = item["entry"], item["feed"]
            title = _entry_get(entry, "title")
            if not title or not str(title).strip():
                continue
            title = str(title).strip()
            freshness = _freshness(_entry_get(entry, "published_parsed"))
            tags = _entry_get(entry, "tags") or []
            keywords = [
                t["term"] if isinstance(t, dict) else getattr(t, "term", "")
                for t in tags
            ]
            keywords = [k for k in keywords if k] or extract_keywords(title)
            trends.append(
                Trend(
                    title=title,
                    source=self.source,
                    source_url=_entry_get(entry, "link"),
                    keywords=keywords,
                    category=ContentCategory.NEWS,
                    popularity_score=round(freshness, 4),
                    # RSS exposes no growth or engagement signal — leave at 0 so
                    # recency isn't double-counted as growth.
                    growth_score=0.0,
                    engagement_score=0.0,
                    confidence=0.4,
                    language=query.language,
                    region=query.region,
                    metadata={"feed": feed},
                )
            )
        return trends
