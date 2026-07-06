"""Email service: template rendering, no-creds behavior, SES send call shape."""

from __future__ import annotations

from typing import Any

import aioboto3
import pytest

from app.core.config import get_settings
from app.services import email as email_service


def test_render_otp_code_contains_code_and_ttl() -> None:
    html = email_service.render_template(
        "otp_code", {"code": "445566", "ttl_minutes": 10, "full_name": None}
    )
    assert "445566" in html
    assert "10 minutes" in html


def test_render_welcome_contains_name_and_cta() -> None:
    html = email_service.render_template(
        "welcome", {"full_name": "Asha Rao", "cta_url": "https://example.com/app/home"}
    )
    assert "Asha Rao" in html
    assert "https://example.com/app/home" in html
    assert "Open Sarathi" in html


def test_render_nudge_contains_title_body_cta() -> None:
    html = email_service.render_template(
        "nudge",
        {
            "full_name": "Asha",
            "title": "Your FD matures soon",
            "body": "Renew for a better rate.",
            "cta_url": "https://example.com/x",
            "cta_label": "Renew now",
        },
    )
    assert "Your FD matures soon" in html
    assert "Renew for a better rate." in html
    assert "Renew now" in html


def test_render_proposal_outreach_contains_event_and_cta() -> None:
    html = email_service.render_template(
        "proposal_outreach",
        {
            "full_name": "Asha",
            "title": "Congrats!",
            "event_headline": "Congrats on the new addition to your family!",
            "body": "Consider a child plan.",
            "cta_url": "https://example.com/y",
            "cta_label": "Explore plans",
        },
    )
    assert "new addition to your family" in html
    assert "Explore plans" in html


def test_text_fallback_strips_tags_and_keeps_content() -> None:
    html = "<p>Hello <b>World</b></p><br>Bye"
    text = email_service._text_fallback(html)
    assert "<" not in text
    assert "Hello" in text
    assert "World" in text
    assert "Bye" in text


async def test_send_templated_renders_subject_from_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _fake_send_email(
        to: str, subject: str, html: str, text: str
    ) -> email_service.EmailResult:
        captured.update(to=to, subject=subject, html=html, text=text)
        return email_service.EmailResult(sent=True, message_id="x")

    monkeypatch.setattr(email_service, "send_email", _fake_send_email)

    result = await email_service.send_templated(
        "to@realmail.co",
        "nudge",
        {
            "full_name": "Asha",
            "title": "Renew your FD",
            "body": "...",
            "cta_url": None,
            "cta_label": None,
        },
    )
    assert captured["to"] == "to@realmail.co"
    assert captured["subject"] == "Renew your FD"
    assert "Renew your FD" in captured["html"]
    assert result.sent is True


async def test_send_email_raises_when_creds_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "aws_access_key_id", None)
    monkeypatch.setattr(settings, "aws_secret_access_key", None)
    with pytest.raises(email_service.EmailNotConfigured):
        await email_service.send_email("a@b.com", "subject", "<p>hi</p>", "hi")


class _FakeSesClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_email(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"MessageId": "fake-message-id"}

    async def __aenter__(self) -> _FakeSesClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSession:
    def __init__(self, fake_client: _FakeSesClient) -> None:
        self._fake_client = fake_client

    def client(self, service_name: str, **kwargs: Any) -> _FakeSesClient:
        assert service_name == "sesv2"
        return self._fake_client


async def test_send_email_calls_ses_with_expected_params(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "aws_access_key_id", "AKIA_TEST")
    monkeypatch.setattr(settings, "aws_secret_access_key", "secret")
    monkeypatch.setattr(settings, "ses_from_address", "no-reply@niheshr.com")

    fake_client = _FakeSesClient()
    monkeypatch.setattr(aioboto3, "Session", lambda: _FakeSession(fake_client))

    result = await email_service.send_email("to@realmail.co", "Subject!", "<p>hi</p>", "hi")

    assert result.sent is True
    assert result.message_id == "fake-message-id"
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["FromEmailAddress"] == "Sarathi <no-reply@niheshr.com>"
    assert call["Destination"] == {"ToAddresses": ["to@realmail.co"]}
    assert call["Content"]["Simple"]["Subject"]["Data"] == "Subject!"
    assert call["Content"]["Simple"]["Body"]["Html"]["Data"] == "<p>hi</p>"
    assert call["Content"]["Simple"]["Body"]["Text"]["Data"] == "hi"
