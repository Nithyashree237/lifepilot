"""Optional SMTP email delivery for reminders.

The app never stores SMTP credentials in the database: they come from the
environment (local ``.env``) or Streamlit secrets (hosted deployment).  Every
attempt is written to the ``email_log`` table so the Settings page can show an
outbox and delivery errors without leaking the password.

The module is deliberately import-safe when SMTP is not configured -- the app
is fully usable without email.
"""

from __future__ import annotations

import html
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Sequence

from lifepilot import config

try:  # pragma: no cover - import guard for isolated tests
    from lifepilot.db import crud
    from lifepilot.db.database import session_scope
except Exception:  # pragma: no cover
    crud = None  # type: ignore[assignment]
    session_scope = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Status helpers (used by Settings and the sidebar)
# ---------------------------------------------------------------------------
def email_status() -> dict[str, Any]:
    """Describe the current SMTP configuration without exposing secrets."""
    configured = config.smtp_configured()
    security = "SSL" if config.SMTP_USE_SSL else "STARTTLS" if config.SMTP_USE_TLS else "none"
    return {
        "configured": configured,
        "host": config.SMTP_HOST,
        "port": config.SMTP_PORT,
        "security": security,
        "sender": config.SMTP_FROM,
        "username": config.SMTP_USER,
        "missing": config.smtp_missing_settings(),
    }


def email_configured() -> bool:
    return config.smtp_configured()


def _connect() -> smtplib.SMTP:
    """Open an SMTP connection using the configured security mode."""
    if config.SMTP_USE_SSL:
        context = ssl.create_default_context()
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT, context=context
        )
    else:
        smtp = smtplib.SMTP(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT
        )
    smtp.ehlo()
    if config.SMTP_USE_TLS and not config.SMTP_USE_SSL:
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
    if config.SMTP_USER:
        smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
    return smtp


def test_connection() -> tuple[bool, str]:
    """Open, authenticate and close a connection without sending anything."""
    if not config.smtp_configured():
        missing = ", ".join(config.smtp_missing_settings()) or "SMTP settings"
        return False, f"SMTP is not configured yet. Missing: {missing}."
    try:
        with _connect() as smtp:
            smtp.noop()
        return True, (
            f"Connected to {config.SMTP_HOST}:{config.SMTP_PORT} "
            f"({email_status()['security']}) and authenticated as {config.SMTP_USER or 'anonymous'}."
        )
    except smtplib.SMTPAuthenticationError as exc:
        return False, (
            "Authentication failed. For Gmail, use a 16-character App Password "
            f"(not your normal password). Server said: {exc.smtp_code} {exc.smtp_error!r}"
        )
    except Exception as exc:  # network, DNS, certificate, timeout...
        return False, f"Connection failed: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _reminder_lines(notifications: Sequence[object]) -> list[str]:
    lines: list[str] = []
    for item in notifications:
        title = getattr(item, "title", "Reminder")
        message = getattr(item, "message", "")
        lines.append(f"- {title}")
        if message:
            lines.append(f"  {message}")
    return lines


def render_reminder_digest(notifications: Sequence[object]) -> tuple[str, str]:
    """Return ``(subject, body)`` for a reminder digest."""
    count = len(notifications)
    subject = f"LifePilot: {count} reminder{'s' if count != 1 else ''}"
    body = "\n".join(
        [
            "LifePilot reminders",
            "=" * 18,
            "",
            *_reminder_lines(notifications),
            "",
            "Open LifePilot to review and mark items as done.",
        ]
    )
    return subject, body


def render_test_email() -> tuple[str, str]:
    """A realistic sample email used by the Settings preview."""
    subject = "LifePilot: email reminders are working"
    body = "\n".join(
        [
            "LifePilot test email",
            "=" * 18,
            "",
            "If you can read this, your reminder emails are set up correctly.",
            "",
            "What LifePilot will email you:",
            "- Electricity bill due in 4 days (Rs. 2,158.75)",
            "- Warranty for AquaPure RO Water Purifier expires 11 Aug 2028",
            "- Rental agreement renewal needs review by 15 Apr 2027",
            "",
            "Reminders are only sent when a deadline enters its reminder window,",
            "and each deadline is emailed at most once per window.",
            "",
            f"Sent by LifePilot {config.APP_NAME}.",
        ]
    )
    return subject, body


def _html_body(title: str, intro: str, lines: Sequence[str]) -> str:
    items = "".join(f"<li>{html.escape(line.lstrip('- '))}</li>" for line in lines if line.strip())
    return f"""\
<html><body style="font-family:Segoe UI,Arial,sans-serif;color:#19192E">
  <div style="max-width:560px;margin:0 auto;padding:24px">
    <div style="background:linear-gradient(120deg,#5B5BD6,#8B5CF6);color:#fff;
                border-radius:14px;padding:18px 22px;font-size:20px;font-weight:700">
      🧭 LifePilot
    </div>
    <h2 style="margin:22px 0 6px">{html.escape(title)}</h2>
    <p style="color:#55557A;margin-top:0">{html.escape(intro)}</p>
    <ul style="line-height:1.6">{items}</ul>
    <p style="color:#9999B0;font-size:12px">
      You received this because LifePilot reminder emails are enabled.
    </p>
  </div>
</body></html>"""


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
def _log(
    to_address: str, subject: str, body: str, status: str, detail: str | None = None
) -> None:
    """Best-effort outbox write; never let logging break delivery."""
    if crud is None or session_scope is None:
        return
    try:
        with session_scope() as session:
            crud.log_email(
                session,
                to_address=to_address,
                subject=subject,
                body=body,
                status=status,
                detail=detail,
            )
    except Exception:  # pragma: no cover - database not initialised
        pass


def send_email(to_address: str, subject: str, body: str) -> tuple[bool, str]:
    """Send an email, returning ``(success, message)`` instead of raising."""
    to_address = (to_address or "").strip()
    if not to_address:
        return False, "No recipient configured."
    if not config.smtp_configured():
        missing = ", ".join(config.smtp_missing_settings()) or "SMTP settings"
        _log(to_address, subject, body, "failed", f"SMTP not configured ({missing})")
        return False, f"SMTP is not configured. Missing: {missing}."

    message = EmailMessage()
    message["From"] = config.SMTP_FROM
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    message.add_alternative(_html_body(subject, "Here is your LifePilot summary.", body.splitlines()), subtype="html")

    try:
        with _connect() as smtp:
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        detail = (
            "Authentication failed. For Gmail, create a 16-character App Password "
            f"(Google Account -> Security -> 2-Step Verification -> App passwords). "
            f"Server said: {exc.smtp_code} {exc.smtp_error!r}"
        )
        _log(to_address, subject, body, "failed", detail)
        return False, detail
    except Exception as exc:
        detail = f"Email failed: {type(exc).__name__}: {exc}"
        _log(to_address, subject, body, "failed", detail)
        return False, detail

    _log(to_address, subject, body, "sent", f"Delivered via {config.SMTP_HOST}:{config.SMTP_PORT}")
    return True, f"Email sent to {to_address}."


def send_reminder_digest(notifications: Sequence[object], to_address: str) -> tuple[bool, str]:
    """Send a single digest for one scheduler run."""
    if not notifications:
        return False, "Nothing to send."
    subject, body = render_reminder_digest(notifications)
    return send_email(to_address, subject, body)


def send_test_email(to_address: str) -> tuple[bool, str]:
    """Send the sample email so a reviewer can verify delivery."""
    subject, body = render_test_email()
    return send_email(to_address, subject, body)
