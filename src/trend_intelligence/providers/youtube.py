"""YouTube Trending provider via the Data API v3 ``videos.list`` (chart=mostPopular).

Requires a free ``YOUTUBE_API_KEY`` (set it in ``.env``). The endpoint costs only
1 quota unit per call (10,000/day free). Until a key is present the provider is
dormant (``is_enabled`` is False) and is skipped — no error, no code change.

    GET https://www.googleapis.com/youtube/v3/videos
        ?part=snippet,statistics&chart=mostPopular&regionCode=US&key=...
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..domain.exceptions import ProviderAuthError, RateLimitError
from ..domain.models import ContentCategory, Trend, TrendQuery, TrendSource
from .base import BaseTrendProvider, extract_keywords

_API_URL = "https://www.googleapis.com/youtube/v3/videos"


def _to_int(stats: dict[str, Any], key: str) -> int:
    try:
        return int(stats.get(key, 0))
    except (TypeError, ValueError):
        return 0


class YouTubeProvider(BaseTrendProvider):
    source = TrendSource.YOUTUBE

    def __init__(
        self,
        *args: Any,
        fetch_json: Callable[[dict[str, Any]], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._fetch_json = fetch_json

    @property
    def is_enabled(self) -> bool:
        return bool(self._config.enabled and self._config.api_key)

    def _default_fetch(self, params: dict[str, Any]) -> Any:
        import httpx

        response = httpx.get(
            _API_URL, params=params, timeout=self._config.timeout_seconds
        )
        if response.status_code in (401, 403):
            raise ProviderAuthError(
                self.source.value,
                f"auth/quota error {response.status_code}: {response.text[:200]}",
            )
        if response.status_code == 429:
            raise RateLimitError(self.source.value, "rate limited")
        response.raise_for_status()
        return response.json()

    def _fetch_raw(self, query: TrendQuery) -> list[dict[str, Any]]:
        limit = min(self._config.max_trends, query.max_trends_per_provider)
        region = self._config.options.get("region_code", query.region or "US")
        params = {
            "part": "snippet,statistics",
            "chart": "mostPopular",
            "regionCode": region,
            "maxResults": min(limit, 50),
            "key": self._config.api_key,
        }
        fetch = self._fetch_json or self._default_fetch
        try:
            data = fetch(params)
        except (ProviderAuthError, RateLimitError):
            raise  # auth = non-retryable, rate-limit = retryable; both handled upstream
        except Exception as exc:  # network → retryable
            raise ConnectionError(str(exc)) from exc
        return data.get("items", []) if isinstance(data, dict) else []

    def _normalize(
        self, raw: list[dict[str, Any]], query: TrendQuery
    ) -> list[Trend]:
        if not raw:
            return []
        views = [_to_int(it.get("statistics", {}), "viewCount") for it in raw]
        engagements = [
            _to_int(it.get("statistics", {}), "likeCount")
            + _to_int(it.get("statistics", {}), "commentCount")
            for it in raw
        ]
        max_views = max(views, default=0) or 1
        max_engagement = max(engagements, default=0) or 1

        trends: list[Trend] = []
        for item, view_count, engagement in zip(raw, views, engagements):
            snippet = item.get("snippet", {})
            title = str(snippet.get("title", "")).strip()
            if not title:
                continue
            video_id = item.get("id")
            tags = snippet.get("tags") or []
            keywords = [t for t in tags][:8] or extract_keywords(title)
            trends.append(
                Trend(
                    title=title,
                    source=self.source,
                    source_url=f"https://www.youtube.com/watch?v={video_id}",
                    keywords=keywords,
                    category=ContentCategory.OTHER,  # mixed; LLM refines later
                    popularity_score=round(view_count / max_views, 4),
                    engagement_score=round(engagement / max_engagement, 4),
                    growth_score=0.6,
                    confidence=0.7,
                    language=query.language,
                    region=query.region,
                    metadata={
                        "views": view_count,
                        "channel": snippet.get("channelTitle"),
                        "video_id": video_id,
                    },
                )
            )
        return trends
