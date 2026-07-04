"""Tests for the weekly channel report (Google APIs faked)."""

from __future__ import annotations

from datetime import date

import pytest

from shorts.analytics.cli import main as report_main
from shorts.analytics.models import (
    ChannelSnapshot,
    VideoStat,
    WeeklyReport,
    WeekMetrics,
)
from shorts.analytics.provider import YouTubeAnalyticsProvider
from shorts.analytics.report import build_markdown, summary_line, week_range
from shorts.domain.exceptions import ReportError


# --------------------------------------------------------------------------- #
# Fake Google services (same style as test_shorts_upload.FakeService)
# --------------------------------------------------------------------------- #
class FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeDataService:
    def __init__(self, *, channels=None, videos=None):
        self._channels = channels or {}
        self._videos = videos or {}

    def channels(self):
        service = self

        class _Channels:
            def list(self, *, part, mine):
                return FakeRequest(service._channels)

        return _Channels()

    def videos(self):
        service = self

        class _Videos:
            def list(self, *, part, id):  # noqa: A002 (Google's param name)
                return FakeRequest(service._videos)

        return _Videos()


class FakeAnalyticsService:
    def __init__(self, response):
        self._response = response
        self.queries = []

    def reports(self):
        service = self

        class _Reports:
            def query(self, **kwargs):
                service.queries.append(kwargs)
                return FakeRequest(service._response)

        return _Reports()


def _provider(data=None, analytics=None):
    return YouTubeAnalyticsProvider(
        build_services=lambda: (
            data or FakeDataService(),
            analytics or FakeAnalyticsService({}),
        )
    )


def _metrics(start="2026-06-27", end="2026-07-03", **kw):
    return WeekMetrics(
        start=date.fromisoformat(start), end=date.fromisoformat(end), **kw
    )


def _report(**kw):
    defaults = dict(
        channel=ChannelSnapshot(
            title="DA DAILY SCROLL", subscribers=12, total_views=345, video_count=6
        ),
        this_week=_metrics(
            views=120, watch_minutes=43, subscribers_gained=6, subscribers_lost=1
        ),
        last_week=_metrics("2026-06-20", "2026-06-26", views=80, watch_minutes=30),
        top_videos=[
            VideoStat(
                video_id="abc123",
                title="Test Short",
                views=90,
                average_view_percentage=78.5,
                likes=4,
            )
        ],
    )
    defaults.update(kw)
    return WeeklyReport(**defaults)


# --------------------------------------------------------------------------- #
# week_range
# --------------------------------------------------------------------------- #
def test_week_range_ends_yesterday():
    this_start, this_end, prev_start, prev_end = week_range(date(2026, 7, 4))
    assert (this_start, this_end) == (date(2026, 6, 27), date(2026, 7, 3))
    assert (prev_start, prev_end) == (date(2026, 6, 20), date(2026, 6, 26))


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def test_markdown_includes_totals_deltas_and_links():
    md = build_markdown(_report())
    assert "# DA DAILY SCROLL — Weekly Report" in md
    assert "| 12 | 345 | 6 |" in md
    assert "| Views | 120 | 80 | +40 (+50%) |" in md
    assert "| Net subscribers | 5 | 0 | +5 |" in md  # zero last week: no percent
    assert "[Test Short](https://www.youtube.com/shorts/abc123)" in md
    assert "78.5%" in md


def test_markdown_without_videos_says_so():
    md = build_markdown(_report(top_videos=[]))
    assert "_No video views recorded this week._" in md


def test_summary_line():
    line = summary_line(_report())
    assert line == "Views 120 (+40 (+50%)) | net subs +5 | watch 43 min | subs total 12"


# --------------------------------------------------------------------------- #
# provider
# --------------------------------------------------------------------------- #
def test_channel_snapshot_parses_string_counts():
    data = FakeDataService(
        channels={
            "items": [
                {
                    "snippet": {"title": "DA DAILY SCROLL"},
                    "statistics": {
                        "subscriberCount": "12",
                        "viewCount": "345",
                        "videoCount": "6",
                    },
                }
            ]
        }
    )
    snapshot = _provider(data=data).channel_snapshot()
    assert snapshot == ChannelSnapshot(
        title="DA DAILY SCROLL", subscribers=12, total_views=345, video_count=6
    )


def test_channel_snapshot_without_channel_raises():
    with pytest.raises(ReportError):
        _provider(data=FakeDataService(channels={"items": []})).channel_snapshot()


def test_week_metrics_maps_by_column_header():
    # Headers deliberately reordered vs the request: mapping must be by name.
    analytics = FakeAnalyticsService(
        {
            "columnHeaders": [
                {"name": "subscribersGained"},
                {"name": "views"},
                {"name": "averageViewPercentage"},
            ],
            "rows": [[6, 120, 78.5]],
        }
    )
    metrics = _provider(analytics=analytics).week_metrics(
        date(2026, 6, 27), date(2026, 7, 3)
    )
    assert metrics.views == 120
    assert metrics.subscribers_gained == 6
    assert metrics.average_view_percentage == 78.5
    assert metrics.likes == 0
    query = analytics.queries[0]
    assert query["ids"] == "channel==MINE"
    assert (query["startDate"], query["endDate"]) == ("2026-06-27", "2026-07-03")


def test_week_metrics_empty_rows_is_zero_week():
    metrics = _provider(analytics=FakeAnalyticsService({"rows": []})).week_metrics(
        date(2026, 6, 27), date(2026, 7, 3)
    )
    assert metrics.views == 0
    assert metrics.net_subscribers == 0


def test_top_videos_joins_titles():
    analytics = FakeAnalyticsService({"rows": [["abc123", 90, 78.5, 4]]})
    data = FakeDataService(
        videos={"items": [{"id": "abc123", "snippet": {"title": "Test Short"}}]}
    )
    videos = _provider(data=data, analytics=analytics).top_videos(
        date(2026, 6, 27), date(2026, 7, 3), 5
    )
    assert videos == [
        VideoStat(
            video_id="abc123",
            title="Test Short",
            views=90,
            average_view_percentage=78.5,
            likes=4,
        )
    ]
    assert analytics.queries[0]["dimensions"] == "video"
    assert analytics.queries[0]["maxResults"] == 5


def test_top_videos_title_join_is_best_effort():
    analytics = FakeAnalyticsService({"rows": [["abc123", 90, 78.5, 4]]})

    class _BrokenData(FakeDataService):
        def videos(self):
            raise RuntimeError("quota")

    videos = _provider(data=_BrokenData(), analytics=analytics).top_videos(
        date(2026, 6, 27), date(2026, 7, 3), 5
    )
    assert videos[0].video_id == "abc123"
    assert videos[0].title == ""


def test_analytics_error_wrapped():
    analytics = FakeAnalyticsService(RuntimeError("boom"))
    with pytest.raises(ReportError):
        _provider(analytics=analytics).week_metrics(date(2026, 6, 27), date(2026, 7, 3))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
class _FakeProvider:
    def __init__(self, **_):
        pass

    def channel_snapshot(self):
        return ChannelSnapshot(title="DA DAILY SCROLL", subscribers=12)

    def week_metrics(self, start, end):
        return WeekMetrics(start=start, end=end, views=120)

    def top_videos(self, start, end, limit):
        return []


def test_cli_writes_report_and_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("shorts.analytics.cli.YouTubeAnalyticsProvider", _FakeProvider)
    config = tmp_path / "shorts.yaml"
    config.write_text(
        f"report:\n  output_dir: {(tmp_path / 'reports').as_posix()}\n",
        encoding="utf-8",
    )
    assert report_main(["--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "SUMMARY: Views 120" in out
    reports = list((tmp_path / "reports").glob("weekly-*.md"))
    assert len(reports) == 1
    assert "Weekly Report" in reports[0].read_text(encoding="utf-8")
