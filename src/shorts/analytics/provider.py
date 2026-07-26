"""Read-only YouTube channel analytics (Analytics API v2 + Data API v3).

Deliberately split by auth type to keep the OAuth surface as small as possible:

* **Analytics API** — private per-channel metrics, so OAuth is unavoidable. Uses
  ``yt-analytics.readonly`` alone, with a SEPARATE token cache so the upload
  token keeps its narrow ``youtube.upload`` scope.
* **Data API** — only ever reads *public* data here (channel totals and video
  titles), so it authenticates with a plain API key. Doing this over OAuth would
  mean requesting ``youtube.readonly``, a second sensitive scope, purely to read
  things anyone can read anonymously.

The YouTube Analytics API must be enabled in the same Google Cloud project as
the OAuth client, else queries 403 with accessNotConfigured. Both services are
injectable so tests never touch Google.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from trend_intelligence.logging.setup import get_logger

from ..domain.exceptions import ReportError
from .models import ChannelSnapshot, VideoStat, WeekMetrics

# Analytics only. `youtube.readonly` is deliberately NOT here: the Data API
# calls below read public data and go through an API key instead.
_SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]

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


_REAUTH_HINT = (
    "mint one locally with `python scripts/reauth_youtube.py --scopes report` "
    "and paste it into the YOUTUBE_REPORT_TOKEN_JSON secret"
)


def _is_interactive() -> bool:
    """Whether a browser consent could actually be completed here.

    False on a GitHub runner and under Task Scheduler — both of which would
    otherwise sit on ``run_local_server`` until the job times out.
    """
    return bool(getattr(sys.stdin, "isatty", lambda: False)())


class YouTubeAnalyticsProvider:
    def __init__(
        self,
        *,
        client_secrets_path: str | None = None,
        token_path: str = ".secrets/youtube_report_token.json",
        api_key: str | None = None,
        channel_id: str | None = None,
        build_services: Callable[[], tuple[Any, Any]] | None = None,
    ) -> None:
        self._client_secrets_path = client_secrets_path
        self._token_path = Path(token_path)
        self._api_key = api_key
        self._channel_id = channel_id
        self._build_services = build_services
        self._services: tuple[Any, Any] | None = None
        self._logger = get_logger("shorts.report")

    # --- auth / service construction (mirrors upload provider) ---------- #
    def _get_services(self) -> tuple[Any, Any]:
        """Return ``(data_service, analytics_service)``, building once.

        ``data_service`` is None when no API key is configured — it only serves
        optional public lookups, so the report degrades rather than fails.
        """
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
        # Checked before the Google imports so it stays a fast, readable failure:
        # an unset/empty YOUTUBE_REPORT_TOKEN_JSON secret would otherwise reach
        # run_local_server and hang the job until its timeout.
        if not self._token_path.exists() and not _is_interactive():
            raise ReportError(
                f"no report OAuth token at {self._token_path} and no terminal to "
                f"consent in — {_REAUTH_HINT}"
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
            try:
                # Parsed here rather than via from_authorized_user_file so the
                # token survives the round-trip through a GitHub secret: utf-8-sig
                # drops the BOM a Windows copy-paste can prepend, and .strip()
                # the stray whitespace. Both otherwise fail at char 0.
                info = json.loads(
                    self._token_path.read_text(encoding="utf-8-sig").strip()
                )
                creds = Credentials.from_authorized_user_info(info, _SCOPES)
            except Exception as exc:
                raise ReportError(
                    f"the report OAuth token at {self._token_path} is not valid "
                    f"authorized-user JSON ({exc}) — check the secret holds the "
                    f"whole file; {_REAUTH_HINT}"
                ) from exc
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as exc:
                    # invalid_grant: revoked, or minted without offline access so
                    # it was never durable. Unrecoverable without a fresh consent.
                    raise ReportError(
                        f"Google rejected the report OAuth token at "
                        f"{self._token_path} ({exc}) — it has been revoked or was "
                        f"never durable; {_REAUTH_HINT}"
                    ) from exc
            else:
                # Present but unrefreshable (revoked, or minted without a
                # refresh_token). Same reasoning as the check above.
                if not _is_interactive():
                    raise ReportError(
                        f"the report OAuth token at {self._token_path} cannot be "
                        f"refreshed and no terminal is available — {_REAUTH_HINT}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._client_secrets_path, _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
        # The Data API gets the API key, never `creds` — that is the whole point
        # of dropping youtube.readonly.
        data = (
            build("youtube", "v3", developerKey=self._api_key)
            if self._api_key
            else None
        )
        self._services = (data, build("youtubeAnalytics", "v2", credentials=creds))
        return self._services

    # --- queries --------------------------------------------------------- #
    def channel_snapshot(self) -> ChannelSnapshot | None:
        """Lifetime channel totals, or None when not configured.

        Needs an API key and a channel id (``mine=True`` is not available
        without OAuth). Unconfigured is a soft skip — the week-over-week body of
        the report, which is the point, does not depend on this. A configured
        but failing lookup is loud: that is a wrong id or a bad key.
        """
        data, _ = self._get_services()
        if data is None or not self._channel_id:
            self._logger.warning(
                "channel_totals_skipped",
                reason="set YOUTUBE_API_KEY and report.channel_id to include them",
            )
            return None
        try:
            response = (
                data.channels()
                .list(part="snippet,statistics", id=self._channel_id)
                .execute()
            )
        except ReportError:
            raise
        except Exception as exc:
            raise ReportError(f"channel statistics query failed: {exc}") from exc
        items = response.get("items") or []
        if not items:
            raise ReportError(f"no channel found with id {self._channel_id!r}")
        stats = items[0].get("statistics") or {}
        return ChannelSnapshot(
            title=(items[0].get("snippet") or {}).get("title", ""),
            # Public subscriber counts are rounded to 3 significant figures above
            # 1,000, and omitted entirely when the channel hides them.
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
        if data is None:  # no API key: the report falls back to bare video ids
            return
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
