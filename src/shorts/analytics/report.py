"""Week-range math and rendering for the weekly report (pure logic).

Two renderers over the same numbers: ``build_markdown`` (the archived file) and
``build_html`` (the emailed body). Both share ``_week_rows`` so the deltas are
computed in exactly one place.
"""

from __future__ import annotations

from datetime import date, timedelta
from html import escape

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


# (label, attribute, higher_is_better). Only "subscribers lost" is inverted —
# a rise there is a bad week, and the HTML colouring must not call it green.
_INT_METRICS: list[tuple[str, str, bool]] = [
    ("Views", "views", True),
    ("Watch time (min)", "watch_minutes", True),
    ("Subscribers gained", "subscribers_gained", True),
    ("Subscribers lost", "subscribers_lost", False),
    ("Net subscribers", "net_subscribers", True),
    ("Likes", "likes", True),
    ("Comments", "comments", True),
    ("Shares", "shares", True),
]


def _direction(this: float, last: float, higher_is_better: bool) -> int:
    """``1`` better, ``-1`` worse, ``0`` flat — for the HTML delta colour."""
    if this == last:
        return 0
    improved = this > last if higher_is_better else this < last
    return 1 if improved else -1


def _week_rows(
    this: WeekMetrics, last: WeekMetrics
) -> list[tuple[str, str, str, str, int]]:
    """``(label, this, last, delta, direction)`` — the single source of truth
    for both renderers."""
    rows: list[tuple[str, str, str, str, int]] = []
    for label, attr, higher_is_better in _INT_METRICS:
        cur, prev = getattr(this, attr), getattr(last, attr)
        rows.append(
            (
                label,
                f"{cur:,}",
                f"{prev:,}",
                _int_delta(cur, prev),
                _direction(cur, prev, higher_is_better),
            )
        )
    for label, attr, unit, suffix in [
        ("Avg view duration", "average_view_duration_seconds", "s", "s"),
        ("Avg viewed", "average_view_percentage", "pp", "%"),
    ]:
        cur, prev = getattr(this, attr), getattr(last, attr)
        rows.append(
            (
                label,
                f"{cur:.1f}{suffix}",
                f"{prev:.1f}{suffix}",
                _float_delta(cur, prev, unit),
                _direction(cur, prev, True),
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
        for metric, cur, prev, delta, _ in _week_rows(tw, lw)
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


# --- HTML (emailed body) ------------------------------------------------- #
# Inline styles only, table-based layout: Gmail strips <style> blocks and
# Outlook/Word ignores flexbox and grid.
_FONT = "font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_TH = (
    f"{_FONT};font-size:11px;font-weight:600;text-transform:uppercase;"
    "letter-spacing:.05em;color:#5b6472;padding:10px;border-bottom:2px solid "
    "#d8dee6"
)
_TD = (
    f"{_FONT};font-size:14px;color:#1b1f24;padding:10px;border-bottom:1px solid #eceff3"
)
_DELTA_COLORS = {1: "#177245", -1: "#b3261e", 0: "#5b6472"}


def _cell(content: str, *, style: str, align: str = "left") -> str:
    return f'<td style="{style};text-align:{align}">{content}</td>'


def _head(label: str, *, align: str = "left") -> str:
    return f'<th style="{_TH};text-align:{align}">{escape(label)}</th>'


def build_html(report: WeeklyReport) -> str:
    """The emailed body — same numbers as ``build_markdown``, readable in a
    mail client (markdown tables render as raw pipes in Outlook)."""
    tw, lw, ch = report.this_week, report.last_week, report.channel
    title = escape(ch.title or "Channel")

    week_rows = "".join(
        "<tr>"
        + _cell(escape(metric), style=_TD)
        + _cell(f"<strong>{cur}</strong>", style=_TD, align="right")
        + _cell(prev, style=f"{_TD};color:#5b6472", align="right")
        + _cell(
            delta,
            style=f"{_TD};color:{_DELTA_COLORS[direction]};font-weight:600",
            align="right",
        )
        + "</tr>"
        for metric, cur, prev, delta, direction in _week_rows(tw, lw)
    )

    if report.top_videos:
        video_rows = "".join(
            "<tr>"
            + _cell(str(i), style=f"{_TD};color:#5b6472", align="right")
            + _cell(
                f'<a href="https://www.youtube.com/shorts/{escape(v.video_id)}" '
                f'style="color:#0b57d0;text-decoration:none">'
                f"{escape(v.title or v.video_id)}</a>",
                style=_TD,
            )
            + _cell(f"{v.views:,}", style=_TD, align="right")
            + _cell(f"{v.average_view_percentage:.1f}%", style=_TD, align="right")
            + _cell(f"{v.likes:,}", style=_TD, align="right")
            + "</tr>"
            for i, v in enumerate(report.top_videos, start=1)
        )
        top_videos = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="border-collapse:collapse;width:100%">'
            "<tr>"
            + _head("#", align="right")
            + _head("Video")
            + _head("Views", align="right")
            + _head("Avg viewed", align="right")
            + _head("Likes", align="right")
            + "</tr>"
            + video_rows
            + "</table>"
        )
    else:
        top_videos = (
            f'<p style="{_FONT};font-size:14px;color:#5b6472;margin:0">'
            "No video views recorded this week.</p>"
        )

    return f"""\
<div style="background:#f4f6f8;padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="border-collapse:collapse;max-width:640px;margin:0 auto;background:#ffffff;
 border:1px solid #e3e8ee;border-radius:10px">
<tr><td style="padding:24px">
  <h1 style="{_FONT};font-size:20px;color:#1b1f24;margin:0 0 4px">{title}</h1>
  <p style="{_FONT};font-size:13px;color:#5b6472;margin:0 0 20px">
    Week of <strong>{tw.start}</strong> &rarr; <strong>{tw.end}</strong>,
    compared with {lw.start} &rarr; {lw.end}
  </p>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
   style="border-collapse:collapse;width:100%;background:#f8fafc;
   border:1px solid #e3e8ee;border-radius:8px;margin:0 0 24px">
    <tr>
      <td style="{_TD};border-bottom:none;text-align:center">
        <div style="font-size:22px;font-weight:700">{ch.subscribers:,}</div>
        <div style="font-size:11px;color:#5b6472;text-transform:uppercase">Subscribers</div>
      </td>
      <td style="{_TD};border-bottom:none;text-align:center">
        <div style="font-size:22px;font-weight:700">{ch.total_views:,}</div>
        <div style="font-size:11px;color:#5b6472;text-transform:uppercase">Total views</div>
      </td>
      <td style="{_TD};border-bottom:none;text-align:center">
        <div style="font-size:22px;font-weight:700">{ch.video_count:,}</div>
        <div style="font-size:11px;color:#5b6472;text-transform:uppercase">Videos</div>
      </td>
    </tr>
  </table>

  <h2 style="{_FONT};font-size:15px;color:#1b1f24;margin:0 0 8px">Week over week</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
   style="border-collapse:collapse;width:100%;margin:0 0 24px">
    <tr>{_head("Metric")}{_head("This week", align="right")}\
{_head("Last week", align="right")}{_head("Change", align="right")}</tr>
    {week_rows}
  </table>

  <h2 style="{_FONT};font-size:15px;color:#1b1f24;margin:0 0 8px">Top videos this week</h2>
  {top_videos}

  <p style="{_FONT};font-size:12px;color:#8a929e;margin:24px 0 0;
   border-top:1px solid #eceff3;padding-top:12px">
    YouTube Analytics data can lag up to ~48h; the most recent days may still be
    settling. The full markdown report is attached.
  </p>
</td></tr>
</table>
</div>
"""


def summary_line(report: WeeklyReport) -> str:
    """One glanceable line for the completion toast / log."""
    tw, lw = report.this_week, report.last_week
    return (
        f"Views {tw.views:,} ({_int_delta(tw.views, lw.views)}) | "
        f"net subs {tw.net_subscribers:+,} | "
        f"watch {tw.watch_minutes:,} min | "
        f"subs total {report.channel.subscribers:,}"
    )
