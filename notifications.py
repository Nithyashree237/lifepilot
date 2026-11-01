"""Optional SMTP email delivery for reminders."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Sequence

from lifepilot import config

try:  # pragma: no cover - trivial import guard
    from lifepilot.db.models import Notification
except Exception:  # pragma: no cover
    Notification = object  # type: ignore[assignment,misc]


def email_configured() -> bool:
    return config.smtp_configured() and bool(config.SMTP_USER or config.SMTP_HOST)


def send_email(to_address: str, subject: str, body: str) -> tuple[bool, str]:
    """Send an email, returning ``(success, message)`` instead of raising."""
    if not to_address:
        return False, "No recipient configured."
    if not email_configured():
        return False, "SMTP is not configured."
    message = EmailMessage()
    message["From"] = config.SMTP_FROM
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            if config.SMTP_USE_TLS:
                smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(message)
        return True, "Email sent."
    except Exception as exc:
        return False, f"Email failed: {exc}"


def send_reminder_digest(notifications: Sequence[object], to_address: str) -> tuple[bool, str]:
    """Send a single digest for one scheduler run."""
    if not notifications:
        return False, "Nothing to send."
    lines = ["LifePilot reminders", "=" * 18, ""]
    for item in notifications:
        title = getattr(item, "title", "Reminder")
        message = getattr(item, "message", "")
        lines.append(f"- {title}")
        if message:
            lines.append(f"  {message}")
    lines += ["", "Open LifePilot to review and mark items as done."]
    subject = f"LifePilot: {len(notifications)} reminder{'s' if len(notifications) != 1 else ''}"
    return send_email(to_address, subject, "\n".join(lines))
