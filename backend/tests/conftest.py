"""Root test configuration.

Belt-and-suspenders safety net: no test may ever make a real AWS SES call,
regardless of whether real AWS credentials happen to be present in the
environment or which recipient address a code path uses. Sending to synthetic
sim personas (``@sarathi-sim.example``) hard-bounces and hurts the account's
sender reputation, and a real send to anyone from a test is never intended.

Every test transparently gets ``app.services.email.send_email`` replaced with a
no-op that returns a successful-looking result without touching the network. The
email service's own unit tests (``test_email_service``) opt out, since they
assert the real send logic against their own mocked SES client.
"""

from __future__ import annotations

import pytest

from app.services import email as email_service


@pytest.fixture(autouse=True)
def _block_real_email(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    module = request.module.__name__ if request.module is not None else ""
    if module.endswith("test_email_service"):
        return

    async def _noop_send_email(
        to: str, subject: str, html: str, text: str
    ) -> email_service.EmailResult:
        return email_service.EmailResult(sent=True, message_id="test-noop")

    monkeypatch.setattr(email_service, "send_email", _noop_send_email)
