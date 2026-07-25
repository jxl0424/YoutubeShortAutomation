"""Weekly channel-growth reporting (YouTube Analytics API).

Standalone from the generation pipeline: ``shorts-report`` (or
``python -m shorts.analytics``) queries the channel's last two weeks of
metrics, writes a markdown report and emails it. See
``.github/workflows/weekly-report.yml`` for the Monday schedule and
``scripts/run_weekly_report.ps1`` for the local wrapper.
"""

from .mailer import build_message, send_report_email
from .models import ChannelSnapshot, VideoStat, WeeklyReport, WeekMetrics
from .provider import YouTubeAnalyticsProvider
from .report import build_html, build_markdown, summary_line, week_range

__all__ = [
    "ChannelSnapshot",
    "VideoStat",
    "WeekMetrics",
    "WeeklyReport",
    "YouTubeAnalyticsProvider",
    "build_html",
    "build_markdown",
    "build_message",
    "send_report_email",
    "summary_line",
    "week_range",
]
