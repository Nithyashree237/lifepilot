"""Tests for the optional email feature and its outbox."""

from __future__ import annotations

from typing import Any

import pytest

from lifepilot import notifications as mail
from lifepilot.db import crud


class _FakeSMTP:
    """Minimal stand-in for smtplib.SMTP."""

    def __init__(self) -> None:
        self.sent: list[Any] = []

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False

    def ehlo(self) -> None:
        return None

    def noop(self) -> None:
        return None

    def login(self, _user: str, _password: str) -> None:
        return None

    def starttls(self, context: Any = None) -> None:
        return None

    def send_message(self, message: Any) -> None:
        self.sent.append(message)


@pytest.fixture()
def smtp_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail.config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(mail.config, "SMTP_PORT", 587)
    monkeypatch.setattr(mail.config, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(mail.config, "SMTP_PASSWORD", "app-password")
    monkeypatch.setattr(mail.config, "SMTP_FROM", "sender@example.com")


def test_render_reminder_digest_has_subject_and_body() -> None:
    class Reminder:
        title = "Pay electricity bill"
        message = "Due in 4 days"

    subject, body = mail.render_reminder_digest([Reminder()])
    assert subject == "LifePilot: 1 reminder"
    assert "Pay electricity bill" in body
    assert "Due in 4 days" in body


def test_render_test_email() -> None:
    subject, body = mail.render_test_email()
    assert "working" in subject.lower()
    assert "reminder emails" in body.lower()


def test_email_status_lists_missing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail.config, "SMTP_HOST", "")
    monkeypatch.setattr(mail.config, "SMTP_USER", "")
    monkeypatch.setattr(mail.config, "SMTP_PASSWORD", "")
    monkeypatch.setattr(mail.config, "SMTP_FROM", "")
    status = mail.email_status()
    assert status["configured"] is False
    assert "LIFEPILOT_SMTP_HOST" in status["missing"]


def test_unconfigured_send_is_logged_as_failed(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail.config, "SMTP_HOST", "")
    monkeypatch.setattr(mail.config, "SMTP_FROM", "")
    ok, message = mail.send_email("someone@example.com", "Hello", "Body")
    assert ok is False
    assert "not configured" in message.lower()
    entries = crud.list_email_log(session)
    assert entries and entries[0].status == "failed"
    assert entries[0].to_address == "someone@example.com"
    assert entries[0].subject == "Hello"


def test_successful_send_writes_outbox(
    session, smtp_ready: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeSMTP()
    monkeypatch.setattr(mail, "_connect", lambda: fake)

    ok, message = mail.send_email("reader@example.com", "Test subject", "Test body")

    assert ok is True
    assert "sent" in message.lower()
    assert len(fake.sent) == 1
    assert fake.sent[0]["To"] == "reader@example.com"

    entries = crud.list_email_log(session)
    assert entries[0].status == "sent"
    assert entries[0].body == "Test body"


def test_test_connection_reports_auth_failure(
    smtp_ready: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise() -> Any:
        raise mail.smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(mail, "_connect", _raise)
    ok, message = mail.test_connection()
    assert ok is False
    assert "App Password" in message


def test_test_connection_success(
    smtp_ready: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail, "_connect", lambda: _FakeSMTP())
    ok, message = mail.test_connection()
    assert ok is True
    assert "Connected to smtp.example.com" in message


def test_send_reminder_digest_requires_content() -> None:
    ok, message = mail.send_reminder_digest([], "reader@example.com")
    assert ok is False
    assert message == "Nothing to send."
