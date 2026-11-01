"""Reminder checks and the APScheduler background job.

The scheduler runs inside the Streamlit process.  Reminders are persisted as
``notifications`` rows (deduplicated) and optionally emailed as a digest.
"""

from __future__ import annotations

import atexit
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from lifepilot import config
from lifepilot.db import crud
from lifepilot.db.database import session_scope
from lifepilot.db.models import Deadline, Notification
from lifepilot.notifications import send_reminder_digest
from lifepilot.utils import fmt_date

logger = logging.getLogger(__name__)


@dataclass
class ReminderRun:
    checked: int = 0
    created: int = 0
    emailed: bool = False
    errors: list[str] = field(default_factory=list)


def _dedupe_key(deadline: Deadline, overdue: bool) -> str:
    if overdue:
        return f"deadline:{deadline.id}:overdue"
    return f"deadline:{deadline.id}:upcoming:{deadline.due_date.isoformat()}"


def _message(deadline: Deadline) -> str:
    document_name = deadline.document.filename if deadline.document else "document"
    days = deadline.days_remaining
    if days < 0:
        when = f"overdue by {abs(days)} day{'s' if abs(days) != 1 else ''}"
    elif days == 0:
        when = "due today"
    else:
        when = f"due in {days} day{'s' if days != 1 else ''}"
    return f"{deadline.title} ({when}, {fmt_date(deadline.due_date)}). Source: {document_name}."


def check_reminders(
    session: Session,
    *,
    today: date | None = None,
    email_fn=None,
) -> ReminderRun:
    """Create notifications for deadlines inside their reminder window."""
    today = today or date.today()
    run = ReminderRun()
    deadlines = list(
        session.scalars(
            select(Deadline)
            .options(joinedload(Deadline.document))
            .where(Deadline.status == "active")
        ).unique()
    )
    new_notifications: list[Notification] = []
    for deadline in deadlines:
        run.checked += 1
        days_remaining = (deadline.due_date - today).days
        overdue = days_remaining < 0
        if not overdue and days_remaining > max(0, deadline.remind_days_before):
            continue
        key = _dedupe_key(deadline, overdue)
        exists = session.scalar(
            select(Notification.id).where(Notification.dedupe_key == key)
        )
        if exists:
            continue
        title = (
            f"Overdue: {deadline.title}"
            if overdue
            else f"{deadline.title} — "
            + ("due today" if days_remaining == 0 else f"due in {days_remaining} days")
        )
        notification = crud.create_notification(
            session,
            title=title,
            message=_message(deadline),
            document_id=deadline.document_id,
            deadline_id=deadline.id,
            kind="overdue" if overdue else "reminder",
            dedupe_key=key,
        )
        if notification is not None:
            run.created += 1
            new_notifications.append(notification)

    if new_notifications:
        settings = crud.get_settings(session)
        if settings.email_enabled and settings.email_to:
            sender = email_fn or send_reminder_digest
            ok, message = sender(new_notifications, settings.email_to)
            run.emailed = bool(ok)
            if not ok:
                run.errors.append(message)
    return run


def upcoming_notifications(session: Session, *, days: int = 7) -> list[Notification]:
    """Notifications and active deadlines relevant to the in-app banner."""
    horizon = date.today() + timedelta(days=days)
    return list(
        session.scalars(
            select(Notification)
            .where(
                Notification.read.is_(False),
                Notification.created_at >= datetime.now() - timedelta(days=14),
            )
            .order_by(Notification.created_at.desc())
            .limit(20)
        )
    ) + [
        item
        for item in crud.upcoming_deadlines(session, days=days)
        if item.due_date <= horizon
    ]


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------
_scheduler: BackgroundScheduler | None = None


def _scheduled_check() -> None:
    try:
        with session_scope() as session:
            result = check_reminders(session)
            if result.created:
                logger.info("LifePilot created %s reminder(s)", result.created)
            for error in result.errors:
                logger.warning("LifePilot reminder email: %s", error)
    except Exception:
        logger.exception("LifePilot reminder check failed")


def start_scheduler() -> BackgroundScheduler:
    """Start the singleton background scheduler (safe to call repeatedly)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _scheduled_check,
        "interval",
        hours=max(1, config.REMINDER_CHECK_HOURS),
        id="lifepilot-reminders",
        next_run_time=datetime.now() + timedelta(seconds=10),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    atexit.register(stop_scheduler)
    logger.info("LifePilot reminder scheduler started")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def scheduler_status() -> dict[str, object]:
    if _scheduler is None or not _scheduler.running:
        return {"running": False, "next_run": None}
    job = _scheduler.get_job("lifepilot-reminders")
    return {
        "running": True,
        "next_run": job.next_run_time if job else None,
        "interval_hours": config.REMINDER_CHECK_HOURS,
    }


def run_check_now() -> ReminderRun:
    """UI button: run the reminder check immediately."""
    with session_scope() as session:
        return check_reminders(session)
