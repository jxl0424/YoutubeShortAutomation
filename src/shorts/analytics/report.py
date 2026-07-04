"""Week-range math and markdown rendering for the weekly report (pure logic)."""

from __future__ import annotations

from datetime import date, timedelta

from .models import WeeklyReport, WeekMetrics


def week_range(today: date) -> tuple[date, date, date, date]:
    """The last 7 full days (ending yesterday) and the 7 before that.

    Returns ``(this_start, this_end, prev_start, prev_end)``. Anchoring on
    yesterday keeps the window identical no matter what time the scheduled
    task fires.
    """
    this_end = today - timedelta(days=1)
    this_start = this_end - timedelta(days=6)
    prev_end = this_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    return this_start, this_end, prev_start, prev_end


def _int_delta(this: int, last: int) -> str:
    """``+40 (+50%)`` — percent omitted when last week was zero."""
    diff = this - last
    if last == 0:
        return f"{diff:+,}"
    return f"{diff:+,} ({diff / last:+.0%})"


def _float_delta(this: float, last: float, unit: str) -> str:
    return f"{this - last:+.1f}{unit}"


def _week_rows(this: WeekMetrics, last: WeekMetrics) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for label, attr in [
        ("Views", "views"),
        ("Watch time (min)", "watch_minutes"),
        ("Subscribers gained", "subscribers_gained"),
        ("Subscribers lost", "subscribers_lost"),
        ("Net subscribers", "net_subscribers"),
        ("Likes", "likes"),
        ("Comments", "comments"),
        ("Shares", "shares"),
    ]:
        cur, prev = getattr(this, attr), getattr(last, attr)
        rows.append((label, f"{cur:,}", f"{prev:,}", _int_delta(cur, prev)))
    rows.append(
        (
            "Avg view duration",
            f"{this.average_view_duration_seconds:.1f}s",
            f"{last.average_view_duration_seconds:.1f}s",
            _float_delta(
                this.average_view_duration_seconds,
                last.average_view_duration_seconds,
                "s",
            ),
        )
    )
    rows.append(
        (
            "Avg viewed",
            f"{this.average_view_percentage:.1f}%",
            f"{last.average_view_percentage:.1f}%",
            _float_delta(
                this.average_view_percentage, last.average_view_percentage, "pp"
            ),
        )
    )
    return rows


def build_markdown(report: WeeklyReport) -> str:
    tw, lw, ch = report.this_week, report.last_week, report.channel
    lines = [
        f"# {ch.title or 'Channel'} — Weekly Report",
        "",
        f"**Week:** {tw.start} → {tw.end} (compared with {lw.start} → {lw.end})",
        "",
        "## Channel totals",
        "",
        "| Subscribers | Total views | Videos |",
        "| ---: | ---: | ---: |",
        f"| {ch.subscribers:,} | {ch.total_views:,} | {ch.video_count:,} |",
        "",
        "## Week over week",
        "",
        "| Metric | This week | Last week | Change |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {metric} | {cur} | {prev} | {delta} |"
        for metric, cur, prev, delta in _week_rows(tw, lw)
    ]
    lines += ["", "## Top videos this week", ""]
    if report.top_videos:
        lines += [
            "| # | Video | Views | Avg viewed | Likes |",
            "| ---: | --- | ---: | ---: | ---: |",
        ]
        for i, v in enumerate(report.top_videos, start=1):
            title = v.title or v.video_id
            url = f"https://www.youtube.com/shorts/{v.video_id}"
            lines.append(
                f"| {i} | [{title}]({url}) | {v.views:,} "
                f"| {v.average_view_percentage:.1f}% | {v.likes:,} |"
            )
    else:
        lines.append("_No video views recorded this week._")
    lines += [
        "",
        "_YouTube Analytics data can lag up to ~48h; the most recent days may "
        "still be settling._",
        "",
    ]
    return "\n".join(lines)


def summary_line(report: WeeklyReport) -> str:
    """One glanceable line for the completion toast / log."""
    tw, lw = report.this_week, report.last_week
    return (
        f"Views {tw.views:,} ({_int_delta(tw.views, lw.views)}) | "
        f"net subs {tw.net_subscribers:+,} | "
        f"watch {tw.watch_minutes:,} min | "
        f"subs total {report.channel.subscribers:,}"
    )
