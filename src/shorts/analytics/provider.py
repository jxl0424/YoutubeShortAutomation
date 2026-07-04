"""Read-only YouTube channel analytics (Analytics API v2 + Data API v3).

Same OAuth/lazy-import conventions as the upload provider, but with read-only
scopes and a SEPARATE token cache, so the upload token keeps its narrow
``youtube.upload`` scope. First run opens a browser consent; the YouTube
Analytics API must be enabled in the same Google Cloud project as the OAuth
client (else the query 403s with accessNotConfigured). Both services are
injectable so tests never touch Google.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from trend_intelligence.logging.setup import get_logger

from ..domain.exceptions import ReportError
from .models import ChannelSnapshot, VideoStat, WeekMetrics

_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

# One Analytics API metric name per WeekMetrics field, in query order.
_WEEK_METRICS = {
    "views": "views",
    "estimatedMinutesWatched": "watch_minutes",
    "averageViewDuration": "average_view_duration_seconds",
    "averageViewPercentage": "average_view_percentage",
    "subscribersGained": "subscribers_gained",
    "subscribersLost": "subscribers_lost",
    "likes": "likes",
    "comments": "comments",
    "shares": "shares",
}


class YouTubeAnalyticsProvider:
    def __init__(
        self,
        *,
        client_secrets_path: str | None = None,
        token_path: str = ".secrets/youtube_report_token.json",
        build_services: Callable[[], tuple[Any, Any]] | None = None,
    ) -> None:
        self._client_secrets_path = client_secrets_path
        self._token_path = Path(token_path)
        self._build_services = build_services
        self._services: tuple[Any, Any] | None = None
        self._logger = get_logger("shorts.report")

    # --- auth / service construction (mirrors upload provider) ---------- #
    def _get_services(self) -> tuple[Any, Any]:
        """Return ``(data_service, analytics_service)``, building once."""
        if self._services is not None:
            return self._services
        if self._build_services is not None:
            self._services = self._build_services()
            return self._services
        if (
            not self._client_secrets_path
            or not Path(self._client_secrets_path).exists()
        ):
            raise ReportError(
                "YouTube client secrets not found (set YOUTUBE_CLIENT_SECRETS)"
            )
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ReportError(
                "install the 'youtube' extra for report support: pip install -e '.[youtube]'"
            ) from exc

        creds = None
        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._token_path), _SCOPES
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._client_secrets_path, _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
        self._services = (
            build("youtube", "v3", credentials=creds),
            build("youtubeAnalytics", "v2", credentials=creds),
        )
        return self._services

    # --- queries --------------------------------------------------------- #
    def channel_snapshot(self) -> ChannelSnapshot:
        data, _ = self._get_services()
        try:
            response = (
                data.channels().list(part="snippet,statistics", mine=True).execute()
            )
        except ReportError:
            raise
        except Exception as exc:
            raise ReportError(f"channel statistics query failed: {exc}") from exc
        items = response.get("items") or []
        if not items:
            raise ReportError("no channel found for the authorized account")
        stats = items[0].get("statistics") or {}
        return ChannelSnapshot(
            title=(items[0].get("snippet") or {}).get("title", ""),
            subscribers=int(stats.get("subscriberCount", 0)),
            total_views=int(stats.get("viewCount", 0)),
            video_count=int(stats.get("videoCount", 0)),
        )

    def week_metrics(self, start: date, end: date) -> WeekMetrics:
        _, analytics = self._get_services()
        try:
            response = (
                analytics.reports()
                .query(
                    ids="channel==MINE",
                    startDate=start.isoformat(),
                    endDate=end.isoformat(),
                    metrics=",".join(_WEEK_METRICS),
                )
                .execute()
            )
        except ReportError:
            raise
        except Exception as exc:
            raise ReportError(f"analytics query failed: {exc}") from exc

        # Map by column header: the API's column order matches the requested
        # metrics today, but the headers are the documented contract. A brand
        # new channel (or an all-zero week) can return no rows at all.
        fields: dict[str, float] = {}
        rows = response.get("rows") or []
        if rows:
            headers = [col["name"] for col in response.get("columnHeaders", [])]
            for header, value in zip(headers, rows[0], strict=False):
                field = _WEEK_METRICS.get(header)
                if field is not None:
                    fields[field] = value
        return WeekMetrics(start=start, end=end, **fields)

    def top_videos(self, start: date, end: date, limit: int) -> list[VideoStat]:
        data, analytics = self._get_services()
        try:
            response = (
                analytics.reports()
                .query(
                    ids="channel==MINE",
                    startDate=start.isoformat(),
                    endDate=end.isoformat(),
                    metrics="views,averageViewPercentage,likes",
                    dimensions="video",
                    sort="-views",
                    maxResults=limit,
                )
                .execute()
            )
        except ReportError:
            raise
        except Exception as exc:
            raise ReportError(f"top-videos query failed: {exc}") from exc

        rows = response.get("rows") or []
        videos = [
            VideoStat(
                video_id=row[0],
                views=int(row[1]),
                average_view_percentage=float(row[2]),
                likes=int(row[3]),
            )
            for row in rows
        ]
        if videos:
            self._attach_titles(data, videos)
        return videos

    def _attach_titles(self, data: Any, videos: list[VideoStat]) -> None:
        """Join watch-page titles onto the stats (best-effort)."""
        try:
            response = (
                data.videos()
                .list(part="snippet", id=",".join(v.video_id for v in videos))
                .execute()
            )
        except Exception as exc:
            self._logger.warning("video_titles_failed", error=str(exc))
            return
        titles = {
            item["id"]: (item.get("snippet") or {}).get("title", "")
            for item in response.get("items") or []
        }
        for video in videos:
            video.title = titles.get(video.video_id, "")
