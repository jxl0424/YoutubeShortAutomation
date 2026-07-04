"""Command-line entry point for the weekly channel report.

Fetches the last two full weeks of channel analytics and writes a markdown
report to ``report.output_dir``. Progress goes to stderr; stdout carries the
report path and a one-line ``SUMMARY:`` (which the scheduled wrapper surfaces
as a toast).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from trend_intelligence.logging.setup import configure_logging

from ..config.settings import PROJECT_ROOT, ShortsConfig
from ..domain.exceptions import ShortsError
from .models import WeeklyReport
from .provider import YouTubeAnalyticsProvider
from .report import build_markdown, summary_line, week_range


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="shorts-report",
        description="Write a weekly channel-growth report from YouTube Analytics.",
    )
    parser.add_argument(
        "--config", help="Path to the Stage 2 config YAML (default: config/shorts.yaml)"
    )
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(args.log_level, json_logs=True)

    try:
        config = ShortsConfig.load(args.config)
    except ShortsError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    provider = YouTubeAnalyticsProvider(
        client_secrets_path=os.getenv(config.report.client_secrets_env),
        token_path=config.report.token_path,
    )
    this_start, this_end, prev_start, prev_end = week_range(date.today())

    print(f"Fetching channel analytics {this_start} → {this_end}...", file=sys.stderr)
    try:
        report = WeeklyReport(
            channel=provider.channel_snapshot(),
            this_week=provider.week_metrics(this_start, this_end),
            last_week=provider.week_metrics(prev_start, prev_end),
            top_videos=provider.top_videos(
                this_start, this_end, config.report.top_videos
            ),
        )
    except ShortsError as exc:
        print(f"Report failed: {exc}", file=sys.stderr)
        return 1

    # Anchor at the project root (like .state/) so scheduled runs never depend
    # on the working directory.
    out_dir = Path(config.report.output_dir)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"weekly-{this_end}.md"
    out_path.write_text(build_markdown(report), encoding="utf-8")

    print(f"Report: {out_path}")
    print(f"SUMMARY: {summary_line(report)}")
    return 0


if __name__ == "__main__":  # python -m shorts.analytics.cli
    raise SystemExit(main())
