"""Display-name branding for emails (headless StaffLess AI overlay).

Invitation, reset, and verify copy all use ONYX_DEFAULT_APPLICATION_NAME on
the foss MIT path (no enterprise_settings store). These tests do not send mail.
"""

from types import SimpleNamespace

import pytest

from onyx.auth.email_utils import (
    build_user_email_invite,
    send_forgot_password_email,
    send_user_verification_email,
)
from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME


def test_default_application_name_is_staffless_ai() -> None:
    assert ONYX_DEFAULT_APPLICATION_NAME == "StaffLess AI"
    assert "Onyx" not in ONYX_DEFAULT_APPLICATION_NAME


def test_invite_email_uses_staffless_ai_not_onyx() -> None:
    text, html = build_user_email_invite(
        "admin@example.com",
        "new@example.com",
        ONYX_DEFAULT_APPLICATION_NAME,
    )
    assert "StaffLess AI" in text
    assert "StaffLess AI" in html
    assert "join an organization on StaffLess AI" in text
    assert "Onyx" not in text
    assert "Onyx" not in html


def test_invite_email_keeps_custom_application_name() -> None:
    text, html = build_user_email_invite(
        "admin@example.com",
        "new@example.com",
        "Acme Intelligence",
    )
    assert "Acme Intelligence" in text
    assert "Acme Intelligence" in html
    assert ONYX_DEFAULT_APPLICATION_NAME not in text


def test_reset_and_verify_subjects_use_staffless_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def fake_send(
        user_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        mail_from: str = "",
        inline_png: tuple[str, bytes] | None = None,
    ) -> None:
        captured.append(subject)
        assert "StaffLess AI" in subject or "StaffLess AI" in html_body
        assert "Onyx" not in subject
        assert "Onyx" not in html_body

    monkeypatch.setattr("onyx.auth.email_utils.send_email", fake_send)
    monkeypatch.setattr(
        "onyx.auth.email_utils.OnyxRuntime.get_emailable_logo",
        lambda: SimpleNamespace(data=b"png"),
    )

    send_forgot_password_email("user@example.com", "reset-token", tenant_id="")
    send_user_verification_email("user@example.com", "verify-token")

    assert captured == [
        "Reset Your StaffLess AI Password",
        "StaffLess AI Email Verification",
    ]
