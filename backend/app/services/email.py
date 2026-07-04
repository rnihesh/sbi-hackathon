"""Transactional email via AWS SES v2 (aioboto3), Jinja2-rendered templates.

Real sends only: if AWS credentials are absent this raises :class:`EmailNotConfigured`
rather than pretending to succeed. Callers (auth routes, agent tools) must catch that
and record a "skipped, no creds" outcome — never fabricate a fake send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aioboto3
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
)

# Subject line per template, as a `str.format`-style template rendered against the same
# `context` dict passed to `send_templated` (so dynamic subjects like nudge titles work
# without widening the `send_templated(to, template_name, context)` signature).
_SUBJECT_TEMPLATES: dict[str, str] = {
    "otp_code": "Your Sarathi verification code",
    "welcome": "Welcome to Sarathi, {full_name}",
    "nudge": "{title}",
    "proposal_outreach": "{title}",
}


class EmailNotConfigured(Exception):  # noqa: N818 - exact name per architecture contract
    """Raised when SES credentials are absent; callers must catch and degrade gracefully."""


@dataclass(frozen=True)
class EmailResult:
    """Outcome of a real SES send (this type is never constructed for a skipped send)."""

    sent: bool
    message_id: str | None


def _from_header() -> str:
    settings = get_settings()
    return f"Sarathi <{settings.ses_from_address}>"


def _text_fallback(html: str) -> str:
    """Small HTML->text fallback for the multipart body (no extra dependency)."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>|</tr>|</div>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def render_template(template_name: str, context: dict[str, Any]) -> str:
    """Render ``<template_name>.html`` from ``app/services/templates/`` with ``context``."""
    template = _env.get_template(f"{template_name}.html")
    return template.render(**context)


async def send_email(to: str, subject: str, html: str, text: str) -> EmailResult:
    """Send a single transactional email via SES v2.

    Raises :class:`EmailNotConfigured` if AWS credentials are absent. Any other SES
    failure propagates as-is (a real infra error, not something to paper over).
    """
    settings = get_settings()
    if not (settings.aws_access_key_id and settings.aws_secret_access_key):
        raise EmailNotConfigured("AWS SES credentials are not configured")

    session = aioboto3.Session()
    async with session.client(
        "sesv2",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    ) as ses:
        response = await ses.send_email(
            FromEmailAddress=_from_header(),
            Destination={"ToAddresses": [to]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": html, "Charset": "UTF-8"},
                        "Text": {"Data": text, "Charset": "UTF-8"},
                    },
                }
            },
        )
    message_id = response.get("MessageId")
    logger.info("email_sent", to=to, subject=subject, message_id=message_id)
    return EmailResult(sent=True, message_id=message_id)


async def send_templated(to: str, template_name: str, context: dict[str, Any]) -> EmailResult:
    """Render ``template_name`` with ``context`` and send it via SES.

    Raises :class:`EmailNotConfigured` (propagated from :func:`send_email`) if AWS creds
    are absent — callers must catch this, log a warning, and mark the send as
    ``skipped_no_creds`` rather than assuming success.
    """
    subject_template = _SUBJECT_TEMPLATES.get(template_name, "Sarathi")
    subject = subject_template.format(**context)
    html = render_template(template_name, context)
    text = _text_fallback(html)
    return await send_email(to, subject, html, text)
