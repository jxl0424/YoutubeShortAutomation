"""Tests for the weekly channel report (Google APIs faked)."""

from __future__ import annotations

import importlib.util
import json
import smtplib
from datetime import date
from pathlib import Path

import pytest

from shorts.analytics.cli import main as report_main
from shorts.analytics.mailer import send_report_email
from shorts.analytics.models import (
    ChannelSnapshot,
    VideoStat,
    WeeklyReport,
    WeekMetrics,
)
from shorts.analytics.provider import _SCOPES as PROVIDER_SCOPES
from shorts.analytics.provider import YouTubeAnalyticsProvider
from shorts.analytics.report import (
    build_html,
    build_markdown,
    summary_line,
    week_range,
)
from shorts.config.settings import ReportEmailConfig
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
        self.channel_queries: list = []

    def channels(self):
        service = self

        class _Channels:
            def list(self, *, part, id):  # noqa: A002 (Google's param name)
                service.channel_queries.append(id)
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


_DEFAULT = object()  # lets a test pass data=None (i.e. "no API key configured")


def _provider(data=_DEFAULT, analytics=None, **kw):
    kw.setdefault("channel_id", "UC_test")
    return YouTubeAnalyticsProvider(
        build_services=lambda: (
            FakeDataService() if data is _DEFAULT else data,
            analytics or FakeAnalyticsService({}),
        ),
        **kw,
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


def test_markdown_omits_channel_totals_when_unavailable():
    md = build_markdown(_report(channel=None))
    assert "## Channel totals" not in md
    assert "# Channel — Weekly Report" in md  # falls back to a generic heading
    assert "| Views | 120 | 80 | +40 (+50%) |" in md  # the body still stands


def test_summary_line_without_channel_totals():
    assert "subs total" not in summary_line(_report(channel=None))


def test_markdown_without_videos_says_so():
    md = build_markdown(_report(top_videos=[]))
    assert "_No video views recorded this week._" in md


def test_summary_line():
    line = summary_line(_report())
    assert line == "Views 120 (+40 (+50%)) | net subs +5 | watch 43 min | subs total 12"


# --------------------------------------------------------------------------- #
# HTML rendering (the emailed body)
# --------------------------------------------------------------------------- #
GREEN, RED = "#177245", "#b3261e"


def _row_html(html: str, label: str) -> str:
    """The <tr> fragment carrying `label` (rows are emitted one per metric)."""
    start = html.index(label)
    return html[start : html.index("</tr>", start)]


def test_html_carries_the_same_numbers_as_the_markdown():
    html = build_html(_report())
    assert "DA DAILY SCROLL" in html
    assert "+40 (+50%)" in html  # same delta strings as the markdown renderer
    assert "https://www.youtube.com/shorts/abc123" in html
    assert "78.5%" in html
    assert "12" in html and "345" in html  # channel totals


def test_html_escapes_video_titles():
    report = _report(
        top_videos=[
            VideoStat(
                video_id="abc123",
                title='<script>alert("x")</script> & more',
                views=90,
            )
        ]
    )
    html = build_html(report)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "&amp; more" in html


def test_html_colours_a_rise_in_subscribers_lost_as_bad():
    # Every other metric is "higher is better"; losing more subs is not.
    html = build_html(_report())
    assert RED in _row_html(html, "Subscribers lost")
    assert GREEN in _row_html(html, "Views")


def test_html_colours_a_flat_metric_neutrally():
    flat = _metrics(views=10)
    html = build_html(_report(this_week=flat, last_week=_metrics(views=10)))
    row = _row_html(html, "Views")
    assert GREEN not in row and RED not in row


def test_html_omits_channel_totals_when_unavailable():
    html = build_html(_report(channel=None))
    # "Total views" is unique to the totals card ("Subscribers" also appears as
    # the gained/lost week-over-week rows, which must survive).
    assert "Total views" not in html
    assert "Total views" in build_html(_report())
    assert "Week over week" in html
    assert _row_html(html, "Subscribers gained")


def test_html_without_videos_says_so():
    assert "No video views recorded this week." in build_html(_report(top_videos=[]))


# --------------------------------------------------------------------------- #
# mailer
# --------------------------------------------------------------------------- #
class FakeSMTP:
    def __init__(self, *, fail_on: str | None = None):
        self.fail_on = fail_on
        self.logged_in: tuple[str, str] | None = None
        self.sent: list = []
        self.quit_called = False

    def login(self, username, password):
        if self.fail_on == "login":
            raise smtplib.SMTPAuthenticationError(535, b"bad app password")
        self.logged_in = (username, password)

    def send_message(self, message):
        if self.fail_on == "send":
            raise smtplib.SMTPRecipientsRefused({})
        self.sent.append(message)

    def quit(self):
        self.quit_called = True


def _email_config(**kw) -> ReportEmailConfig:
    defaults = dict(
        enabled=True,
        to=["brendan@example.com"],
        username="sender@gmail.com",
        password="app-password",
    )
    defaults.update(kw)
    return ReportEmailConfig(**defaults)


def _send(config, smtp, **kw):
    payload = dict(
        subject="Weekly report",
        html="<p>hello</p>",
        markdown="# hello",
        attachment_name="weekly-2026-07-03.md",
    )
    payload.update(kw)
    return send_report_email(config, smtp_factory=lambda: smtp, **payload)


def test_send_builds_html_alternative_with_markdown_fallback_and_attachment():
    smtp = FakeSMTP()
    recipients = _send(_email_config(to=["a@example.com", "b@example.com"]), smtp)

    assert recipients == ["a@example.com", "b@example.com"]
    assert smtp.logged_in == ("sender@gmail.com", "app-password")
    assert smtp.quit_called
    message = smtp.sent[0]
    assert message["To"] == "a@example.com, b@example.com"
    assert message["From"] == "sender@gmail.com"  # defaults to the SMTP username
    assert message["Subject"] == "Weekly report"
    assert message.get_body(preferencelist=("html",)).get_content() == "<p>hello</p>\n"
    assert "# hello" in message.get_body(preferencelist=("plain",)).get_content()
    attachments = list(message.iter_attachments())
    assert [a.get_filename() for a in attachments] == ["weekly-2026-07-03.md"]
    assert attachments[0].get_content().strip() == "# hello"


def test_send_honours_an_explicit_from_address():
    smtp = FakeSMTP()
    _send(_email_config(from_address="reports@example.com"), smtp)
    assert smtp.sent[0]["From"] == "reports@example.com"


def test_send_can_omit_the_attachment():
    smtp = FakeSMTP()
    _send(_email_config(attach_markdown=False), smtp)
    assert list(smtp.sent[0].iter_attachments()) == []


def test_send_without_recipients_raises():
    with pytest.raises(ReportError, match="REPORT_EMAIL_TO"):
        _send(_email_config(to=[]), FakeSMTP())


def test_send_without_credentials_raises():
    with pytest.raises(ReportError, match="REPORT_SMTP_PASSWORD"):
        _send(_email_config(password=None), FakeSMTP())


def test_send_wraps_an_auth_failure_with_an_actionable_message():
    smtp = FakeSMTP(fail_on="login")
    with pytest.raises(ReportError, match="app password"):
        _send(_email_config(), smtp)
    assert smtp.quit_called  # the connection is closed even when login fails


def test_send_wraps_a_delivery_failure():
    with pytest.raises(ReportError, match="failed"):
        _send(_email_config(), FakeSMTP(fail_on="send"))


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
    # Looked up by id, not mine=True: the Data API call carries an API key, not
    # OAuth, so we never request the sensitive youtube.readonly scope.
    assert data.channel_queries == ["UC_test"]


def test_channel_snapshot_without_channel_raises():
    with pytest.raises(ReportError, match="UC_test"):
        _provider(data=FakeDataService(channels={"items": []})).channel_snapshot()


def test_channel_snapshot_skipped_when_unconfigured():
    # No API key (data service is None) => soft skip, not a failure: the
    # week-over-week body is the point of the report.
    assert _provider(data=None, channel_id="UC_test").channel_snapshot() is None
    # Key present but no channel id => same.
    assert _provider(channel_id="").channel_snapshot() is None


def test_top_videos_without_an_api_key_falls_back_to_bare_ids():
    analytics = FakeAnalyticsService({"rows": [["abc123", 90, 78.5, 4]]})
    videos = _provider(data=None, analytics=analytics).top_videos(
        date(2026, 6, 27), date(2026, 7, 3), 5
    )
    assert videos[0].video_id == "abc123"
    assert videos[0].title == ""


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


def test_missing_token_fails_fast_when_not_interactive(tmp_path, monkeypatch):
    # On a runner there is no browser to consent in: without this guard the job
    # blocks on run_local_server until the workflow timeout kills it, reporting
    # "cancelled" instead of "your token secret is missing".
    monkeypatch.setattr("shorts.analytics.provider._is_interactive", lambda: False)
    secrets = tmp_path / "client_secrets.json"
    secrets.write_text("{}", encoding="utf-8")
    provider = YouTubeAnalyticsProvider(
        client_secrets_path=str(secrets),
        token_path=str(tmp_path / "absent.json"),
    )
    with pytest.raises(ReportError, match="reauth_youtube.py --scopes report"):
        provider.channel_snapshot()


def test_unparseable_token_file_is_reported_clearly(tmp_path, monkeypatch):
    # A truncated paste into the secret used to surface as a raw traceback.
    pytest.importorskip("google.oauth2")  # only present with the 'youtube' extra
    monkeypatch.setattr("shorts.analytics.provider._is_interactive", lambda: False)
    secrets = tmp_path / "client_secrets.json"
    secrets.write_text("{}", encoding="utf-8")
    token = tmp_path / "token.json"
    token.write_text("{not json", encoding="utf-8")
    provider = YouTubeAnalyticsProvider(
        client_secrets_path=str(secrets), token_path=str(token)
    )
    with pytest.raises(ReportError, match="whole file"):
        provider.channel_snapshot()


def test_revoked_token_is_reported_clearly(tmp_path, monkeypatch):
    # The real failure mode: Google answers invalid_grant for a revoked or
    # never-durable refresh token. It used to escape as a raw traceback.
    pytest.importorskip("google.oauth2")
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials

    def _revoked(self, request):
        raise RefreshError("invalid_grant: Bad Request")

    monkeypatch.setattr(Credentials, "refresh", _revoked)
    monkeypatch.setattr("shorts.analytics.provider._is_interactive", lambda: False)

    secrets = tmp_path / "client_secrets.json"
    secrets.write_text("{}", encoding="utf-8")
    token = tmp_path / "token.json"
    token.write_text(
        json.dumps(
            {
                "refresh_token": "stale",
                "client_id": "cid",
                "client_secret": "csecret",
                "token": "expired-access-token",
                "expiry": "2020-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    provider = YouTubeAnalyticsProvider(
        client_secrets_path=str(secrets), token_path=str(token)
    )
    with pytest.raises(ReportError, match="revoked or was never durable"):
        provider.channel_snapshot()


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


def _cli_config(tmp_path, *, email: bool) -> str:
    config = tmp_path / "shorts.yaml"
    body = f"report:\n  output_dir: {(tmp_path / 'reports').as_posix()}\n"
    if email:
        body += "  email:\n    enabled: true\n"
    config.write_text(body, encoding="utf-8")
    return str(config)


@pytest.fixture
def smtp_env(monkeypatch):
    monkeypatch.setenv("REPORT_SMTP_USERNAME", "sender@gmail.com")
    monkeypatch.setenv("REPORT_SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("REPORT_EMAIL_TO", "brendan@example.com")


def test_cli_writes_report_and_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("shorts.analytics.cli.YouTubeAnalyticsProvider", _FakeProvider)
    assert report_main(["--config", _cli_config(tmp_path, email=False)]) == 0
    out = capsys.readouterr().out
    assert "SUMMARY: Views 120" in out
    reports = list((tmp_path / "reports").glob("weekly-*.md"))
    assert len(reports) == 1
    assert "Weekly Report" in reports[0].read_text(encoding="utf-8")


def test_cli_emails_the_report(tmp_path, monkeypatch, capsys, smtp_env):
    monkeypatch.setattr("shorts.analytics.cli.YouTubeAnalyticsProvider", _FakeProvider)
    captured: dict = {}

    def _fake_send(email_config, **kwargs):
        captured["to"] = list(email_config.to)
        captured.update(kwargs)
        return list(email_config.to)

    monkeypatch.setattr("shorts.analytics.cli.send_report_email", _fake_send)

    assert report_main(["--config", _cli_config(tmp_path, email=True)]) == 0
    out = capsys.readouterr().out
    assert "EMAILED: 1 recipient(s)" in out
    # The Actions log for this repo is public — never echo the address.
    assert "brendan@example.com" not in out

    assert captured["to"] == ["brendan@example.com"]
    assert "<table" in captured["html"]
    assert "Weekly Report" in captured["markdown"]
    assert captured["attachment_name"].startswith("weekly-")
    assert captured["attachment_name"].endswith(".md")


def test_cli_no_email_flag_skips_sending(tmp_path, monkeypatch, capsys, smtp_env):
    monkeypatch.setattr("shorts.analytics.cli.YouTubeAnalyticsProvider", _FakeProvider)

    def _unexpected(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("--no-email must not send")

    monkeypatch.setattr("shorts.analytics.cli.send_report_email", _unexpected)

    argv = ["--config", _cli_config(tmp_path, email=True), "--no-email"]
    assert report_main(argv) == 0
    out = capsys.readouterr().out
    assert "EMAILED" not in out
    assert list((tmp_path / "reports").glob("weekly-*.md"))  # file still written


def test_cli_fails_the_run_when_the_email_cannot_be_sent(
    tmp_path, monkeypatch, capsys, smtp_env
):
    # The whole point of the report is landing in an inbox: a swallowed send
    # failure is the bug this change exists to prevent.
    monkeypatch.setattr("shorts.analytics.cli.YouTubeAnalyticsProvider", _FakeProvider)

    def _boom(*args, **kwargs):
        raise ReportError("SMTP authentication failed")

    monkeypatch.setattr("shorts.analytics.cli.send_report_email", _boom)

    assert report_main(["--config", _cli_config(tmp_path, email=True)]) == 1
    captured = capsys.readouterr()
    assert "Report email failed" in captured.err
    # The report file survives, so the run is still diagnosable.
    assert list((tmp_path / "reports").glob("weekly-*.md"))


# --------------------------------------------------------------------------- #
# scripts/reauth_youtube.py — token minting
# --------------------------------------------------------------------------- #
def _reauth_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "reauth_youtube.py"
    spec = importlib.util.spec_from_file_location("reauth_youtube", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reauth_report_scopes_match_the_analytics_provider():
    # The script deliberately duplicates the scope list (it must run without
    # importing src/); this keeps the copy honest.
    assert _reauth_module().SCOPE_SETS["report"]["scopes"] == PROVIDER_SCOPES


def test_report_requests_only_the_analytics_scope():
    # youtube.readonly is a second sensitive scope that Google prompts to verify.
    # The Data API lookups here are public and use an API key instead, so the
    # OAuth grant stays at exactly one scope.
    assert PROVIDER_SCOPES == ["https://www.googleapis.com/auth/yt-analytics.readonly"]
    assert not any("youtube.readonly" in scope for scope in PROVIDER_SCOPES)


def test_reauth_report_token_is_distinct_from_the_upload_token():
    # Clobbering the upload token would silently break the daily publish.
    upload, report = (_reauth_module().SCOPE_SETS[k] for k in ("upload", "report"))
    assert upload["token_name"] != report["token_name"]
    assert upload["secret"] != report["secret"]
    assert not any("upload" in scope for scope in report["scopes"])
