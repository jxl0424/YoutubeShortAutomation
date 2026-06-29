"""Hacker News provider via the official Firebase API (credential-free).

    https://hacker-news.firebaseio.com/v0/topstories.json   → list of story ids
    https://hacker-news.firebaseio.com/v0/item/{id}.json     → one story

No auth and no rate limit. Popularity is scaled from a story's points and
engagement from its comment count, relative to the strongest item in the batch.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..domain.models import ContentCategory, Trend, TrendQuery, TrendSource
from .base import BaseTrendProvider, extract_keywords

_BASE = "https://hacker-news.firebaseio.com/v0"


class HackerNewsProvider(BaseTrendProvider):
    source = TrendSource.HACKER_NEWS

    def __init__(
        self,
        *args: Any,
        fetch_json: Callable[[str], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._fetch_json = fetch_json or self._default_fetch

    def _default_fetch(self, url: str) -> Any:
        import httpx

        response = httpx.get(url, timeout=self._config.timeout_seconds)
        response.raise_for_status()
        return response.json()

    def _fetch_raw(self, query: TrendQuery) -> list[dict[str, Any]]:
        try:
            ids = self._fetch_json(f"{_BASE}/topstories.json")
        except Exception as exc:  # network issue → retryable
            raise ConnectionError(str(exc)) from exc
        if not ids:
            return []

        limit = min(self._config.max_trends, query.max_trends_per_provider)
        target_ids = ids[:limit]
        stories: list[dict[str, Any]] = []
        failures = 0

        # Fetch the individual stories concurrently (each is its own request).
        with ThreadPoolExecutor(max_workers=min(10, max(1, len(target_ids)))) as pool:
            futures = {
                pool.submit(self._fetch_json, f"{_BASE}/item/{sid}.json"): sid
                for sid in target_ids
            }
            for future in as_completed(futures):
                story_id = futures[future]
                try:
                    item = future.result()
                except Exception as exc:
                    self._logger.warning("hn_item_error", id=story_id, error=str(exc))
                    failures += 1
                    continue
                if item and item.get("type") == "story" and item.get("title"):
                    stories.append(item)

        if not stories and failures:
            raise ConnectionError(f"all {failures} Hacker News item fetch(es) failed")
        return stories

    def _normalize(self, raw: list[dict[str, Any]], query: TrendQuery) -> list[Trend]:
        if not raw:
            return []
        max_score = max((s.get("score", 0) for s in raw), default=0) or 1
        max_comments = max((s.get("descendants", 0) for s in raw), default=0) or 1

        trends: list[Trend] = []
        for story in raw:
            title = str(story["title"]).strip()
            if not title:
                continue
            story_id = story.get("id")
            trends.append(
                Trend(
                    title=title,
                    source=self.source,
                    source_url=story.get("url")
                    or f"https://news.ycombinator.com/item?id={story_id}",
                    keywords=extract_keywords(title),
                    category=ContentCategory.TECHNOLOGY,
                    popularity_score=round(story.get("score", 0) / max_score, 4),
                    engagement_score=round(
                        story.get("descendants", 0) / max_comments, 4
                    ),
                    growth_score=0.5,
                    confidence=0.6,
                    language=query.language,
                    region=query.region,
                    metadata={
                        "score": story.get("score", 0),
                        "comments": story.get("descendants", 0),
                        "hn_id": story_id,
                    },
                )
            )
        return trends
