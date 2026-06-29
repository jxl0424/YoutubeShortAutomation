"""Google Trends provider via the public "Trending Now" RSS feed.

Credential-free. pytrends' ``trending_searches`` endpoint was deprecated by
Google (returns 404), so this reads the official Trending Now RSS feed instead:

    https://trends.google.com/trending/rss?geo=US

Each item carries a real popularity signal (``ht:approx_traffic``, e.g.
"10000+") and a related news article URL, which we normalize into the shared
models. Popularity is scaled relative to the most-searched item in the feed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import feedparser

from ..domain.models import ContentCategory, Trend, TrendQuery, TrendSource
from .base import BaseTrendProvider, extract_keywords

_TRAFFIC_RE = re.compile(r"[\d,]+")


def _entry_get(entry: Any, key: str, default: Any = None) -> Any:
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _parse_traffic(raw: Any) -> int:
    """Turn an approx_traffic string like '10,000+' into an int."""
    if not raw:
        return 0
    match = _TRAFFIC_RE.search(str(raw))
    return int(match.group(0).replace(",", "")) if match else 0


class GoogleTrendsProvider(BaseTrendProvider):
    source = TrendSource.GOOGLE_TRENDS
    RSS_URL = "https://trends.google.com/trending/rss"

    def __init__(
        self,
        *args: Any,
        parser: Callable[[str], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._parser = parser or feedparser.parse

    def _feed_url(self) -> str:
        geo = self._config.options.get("geo", "US")
        return f"{self.RSS_URL}?geo={geo}"

    def _fetch_raw(self, query: TrendQuery) -> list[Any]:
        url = self._feed_url()
        try:
            parsed = self._parser(url)
        except Exception as exc:  # network issue → retryable
            raise ConnectionError(str(exc)) from exc

        entries = getattr(parsed, "entries", None) or []
        if getattr(parsed, "bozo", 0) and not entries:
            raise ConnectionError(
                f"google trends feed error: {getattr(parsed, 'bozo_exception', '')}"
            )
        return list(entries)

    def _normalize(self, raw: list[Any], query: TrendQuery) -> list[Trend]:
        if not raw:
            return []
        traffics = [_parse_traffic(_entry_get(e, "ht_approx_traffic")) for e in raw]
        max_traffic = max(traffics, default=0)

        trends: list[Trend] = []
        for entry, traffic in zip(raw, traffics):
            title = _entry_get(entry, "title")
            if not title or not str(title).strip():
                continue
            title = str(title).strip()
            popularity = traffic / max_traffic if max_traffic > 0 else 0.0

            keywords = extract_keywords(title)
            news_title = _entry_get(entry, "ht_news_item_title")
            if news_title:
                keywords = list(
                    dict.fromkeys(keywords + extract_keywords(str(news_title)))
                )[:8]

            trends.append(
                Trend(
                    title=title,
                    source=self.source,
                    # Prefer the related-article URL; the feed's <link> is generic.
                    source_url=_entry_get(entry, "ht_news_item_url")
                    or _entry_get(entry, "link"),
                    keywords=keywords,
                    category=ContentCategory.OTHER,
                    popularity_score=round(popularity, 4),
                    growth_score=0.7,  # appearing in trending implies growth
                    engagement_score=0.0,
                    confidence=0.6,
                    language=query.language,
                    region=query.region,
                    metadata={
                        "approx_traffic": _entry_get(entry, "ht_approx_traffic"),
                        "news_source": _entry_get(entry, "ht_news_item_source"),
                    },
                )
            )
        return trends
