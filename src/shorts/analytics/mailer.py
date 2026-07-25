"""SMTP delivery for the weekly report (standard library only).

The report's whole point is landing in an inbox, so every failure here raises
``ReportError`` and fails the run — a silent no-op is exactly what let the
report go missing for weeks. ``smtp_factory`` is injectable so tests never open
a socket (same convention as ``YouTubeAnalyticsProvider.build_services``).

Sender note: Microsoft retired SMTP basic auth (and app passwords) on
2026-04-30, so an Outlook/Microsoft address cannot authenticate here. Gmail with
a 16-character app password is the shipped default; receiving at Outlook is
unaffected.
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any

from ..config.settings import ReportEmailConfig
from ..domain.exceptions import ReportError

SmtpFactory = Callable[[], Any]


def _default_factory(config: ReportEmailConfig) -> SmtpFactory:
    """STARTTLS on submission ports, implicit TLS when ``starttls`` is off."""
    context = ssl.create_default_context()

    def factory() -> Any:
        if config.starttls:
            client = smtplib.SMTP(
                config.smtp_host, config.smtp_port, timeout=config.timeout_seconds
            )
            client.starttls(context=context)
        else:
            client = smtplib.SMTP_SSL(
                config.smtp_host,
                config.smtp_port,
                timeout=config.timeout_seconds,
                context=context,
            )
        return client

    return factory


def build_message(
    config: ReportEmailConfig,
    *,
    subject: str,
    html: str,
    markdown: str,
    attachment_name: str,
) -> EmailMessage:
    """A multipart/alternative message: markdown as the text fallback, HTML as
    the body, and the raw ``.md`` attached for archiving."""
    sender = config.from_address or config.username or ""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(config.to)
    message.set_content(markdown)
    message.add_alternative(html, subtype="html")
    if config.attach_markdown:
        message.add_attachment(
            markdown.encode("utf-8"),
            maintype="text",
            subtype="markdown",
            filename=attachment_name,
        )
    return message


def send_report_email(
    config: ReportEmailConfig,
    *,
    subject: str,
    html: str,
    markdown: str,
    attachment_name: str,
    smtp_factory: SmtpFactory | None = None,
) -> list[str]:
    """Send the report. Returns the recipients; raises ``ReportError`` on any
    misconfiguration or SMTP failure."""
    if not config.to:
        raise ReportError(
            f"no report recipients configured (set {config.to_env} or report.email.to)"
        )
    if not config.username or not config.password:
        raise ReportError(
            f"SMTP credentials missing (set {config.username_env} and "
            f"{config.password_env})"
        )

    message = build_message(
        config,
        subject=subject,
        html=html,
        markdown=markdown,
        attachment_name=attachment_name,
    )
    factory = smtp_factory or _default_factory(config)
    try:
        client = factory()
        try:
            client.login(config.username, config.password)
            client.send_message(message)
        finally:
            client.quit()
    except ReportError:
        raise
    except smtplib.SMTPAuthenticationError as exc:
        # By far the most likely failure: an expired/revoked app password, or an
        # Outlook sender (basic auth retired 2026-04-30).
        raise ReportError(
            f"SMTP authentication failed for {config.smtp_host} — check "
            f"{config.password_env} is a current app password: {exc}"
        ) from exc
    except Exception as exc:
        raise ReportError(
            f"sending the report via {config.smtp_host}:{config.smtp_port} failed: {exc}"
        ) from exc
    return list(config.to)
