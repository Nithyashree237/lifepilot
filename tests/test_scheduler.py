"""Scheduler reminder and optional email tests."""

from __future__ import annotations

from datetime import date, timedelta

from lifepilot.db import crud
from lifepilot.db.models import Deadline, Document, Notification
from lifepilot.scheduler import check_reminders


def make_deadline(session, *, days_from_today: int, remind_days: int = 7) -> Deadline:
    document = Document(
        filename="bill.pdf", stored_path="bill.pdf", doc_type="bill", status="processed"
    )
    session.add(document)
    session.flush()
    deadline = Deadline(
        document_id=document.id,
        title="Bill payment due",
        due_date=date.today() + timedelta(days=days_from_today),
        kind="payment",
        confidence=0.9,
        remind_days_before=remind_days,
        status="active",
    )
    session.add(deadline)
    session.flush()
    return deadline


def test_reminder_created_once_inside_window(session) -> None:
    make_deadline(session, days_from_today=3)
    first = check_reminders(session, today=date.today())
    session.flush()
    assert first.checked == 1
    assert first.created == 1

    notifications = crud.list_notifications(session)
    assert len(notifications) == 1
    assert "due in 3 days" in notifications[0].title

    second = check_reminders(session, today=date.today())
    session.flush()
    assert second.created == 0
    assert len(crud.list_notifications(session)) == 1


def test_outside_reminder_window_creates_nothing(session) -> None:
    make_deadline(session, days_from_today=20, remind_days=7)
    run = check_reminders(session, today=date.today())
    session.flush()
    assert run.created == 0
    assert crud.list_notifications(session) == []


def test_overdue_reminder(session) -> None:
    make_deadline(session, days_from_today=-2)
    run = check_reminders(session, today=date.today())
    session.flush()
    assert run.created == 1
    notification = crud.list_notifications(session)[0]
    assert notification.kind == "overdue"
    assert notification.title.startswith("Overdue:")
    assert "overdue by 2 days" in notification.message


def test_email_digest_is_sent_when_enabled(session) -> None:
    settings = crud.get_settings(session)
    settings.email_enabled = True
    settings.email_to = "user@example.com"
    make_deadline(session, days_from_today=2)
    sent = {}

    def fake_email(notifications, to_address):
        sent["count"] = len(notifications)
        sent["to"] = to_address
        return True, "sent"

    run = check_reminders(session, today=date.today(), email_fn=fake_email)
    session.flush()
    assert run.created == 1
    assert run.emailed is True
    assert sent == {"count": 1, "to": "user@example.com"}


def test_notifications_can_be_marked_read(session) -> None:
    make_deadline(session, days_from_today=1)
    check_reminders(session, today=date.today())
    session.flush()
    notification = crud.list_notifications(session, unread_only=True)[0]
    crud.mark_notification_read(session, notification.id)
    session.flush()
    refreshed = session.get(Notification, notification.id)
    assert refreshed.read is True
    assert crud.list_notifications(session, unread_only=True) == []
