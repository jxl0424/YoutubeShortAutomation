"""Command-line entry point for the weekly channel report.

Fetches the last two full weeks of channel analytics, writes a markdown report
to ``report.output_dir`` and emails it (``report.email``). Progress goes to
stderr; stdout carries the report path and a one-line ``SUMMARY:`` (which the
scheduled wrapper surfaces as a toast).

A failed send fails the run. The report exists to land in an inbox, so treating
delivery as best-effort is what let it go missing for weeks unnoticed — a
non-zero exit is what turns GitHub's failed-workflow email into the alarm. Use
``--no-email`` for a local run that only writes the file.
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
from ..domain.exceptions import ReportError, ShortsError
from .mailer import send_report_email
from .models import WeeklyReport
from .provider import YouTubeAnalyticsProvider
from .report import build_html, build_markdown, summary_line, week_range


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="shorts-report",
        description="Write a weekly channel-growth report from YouTube Analytics.",
    )
    parser.add_argument(
        "--config", help="Path to the Stage 2 config YAML (default: config/shorts.yaml)"
    )
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Write the report file only; skip the email (local dry run)",
    )
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
    markdown = build_markdown(report)
    out_path.write_text(markdown, encoding="utf-8")

    print(f"Report: {out_path}")
    print(f"SUMMARY: {summary_line(report)}")

    email = config.report.email
    if args.no_email or not email.enabled:
        return 0
    try:
        recipients = send_report_email(
            email,
            subject=f"{email.subject_prefix}: {this_start} to {this_end}",
            html=build_html(report),
            markdown=markdown,
            attachment_name=out_path.name,
        )
    except ReportError as exc:
        print(f"Report email failed: {exc}", file=sys.stderr)
        return 1
    # Count only — the GitHub Actions log for this repo is public.
    print(f"EMAILED: {len(recipients)} recipient(s)")
    return 0


if __name__ == "__main__":  # python -m shorts.analytics.cli
    raise SystemExit(main())
