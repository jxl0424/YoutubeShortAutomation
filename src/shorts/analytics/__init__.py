"""Weekly channel-growth reporting (YouTube Analytics API).

Standalone from the generation pipeline: ``shorts-report`` (or
``python -m shorts.analytics``) queries the channel's last two weeks of
metrics and writes a markdown report. See ``scripts/run_weekly_report.ps1``
for the scheduled wrapper.
"""

from .models import ChannelSnapshot, VideoStat, WeeklyReport, WeekMetrics
from .provider import YouTubeAnalyticsProvider
from .report import build_markdown, summary_line, week_range

__all__ = [
    "ChannelSnapshot",
    "VideoStat",
    "WeekMetrics",
    "WeeklyReport",
    "YouTubeAnalyticsProvider",
    "build_markdown",
    "summary_line",
    "week_range",
]
