"""iCalendar (.ics) export for LifePilot deadlines.

The output imports cleanly into Google Calendar, Outlook and Apple Calendar.
Each event includes a display alarm ``remind_days_before`` days ahead.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Sequence

from icalendar import Alarm, Calendar, Event

PRODID = "-//LifePilot//Deadline Export//EN"


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _document_name(item: Any) -> str:
    document = _field(item, "document")
    if document is not None:
        return str(_field(document, "filename", "") or "")
    return str(_field(item, "document_name", "") or "")


def build_calendar(
    deadlines: Iterable[Any],
    *,
    calendar_name: str = "LifePilot Deadlines",
    include_alarms: bool = True,
) -> bytes:
    """Serialize deadlines (DB rows or dicts) to iCalendar bytes."""
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", calendar_name)

    for item in deadlines:
        due_date = _as_date(_field(item, "due_date"))
        if due_date is None:
            continue
        title = str(_field(item, "title", "LifePilot deadline"))
        kind = str(_field(item, "kind", "deadline") or "deadline")
        confidence = _field(item, "confidence", None)
        document_name = _document_name(item)
        deadline_id = _field(item, "id", None)
        source_text = str(_field(item, "source_text", "") or "")

        event = Event()
        event.add("uid", f"lifepilot-{deadline_id or uuid.uuid4().hex}@lifepilot.local")
        event.add("dtstamp", datetime.now(timezone.utc))
        event.add("dtstart", due_date)
        event.add("dtend", due_date + timedelta(days=1))
        event.add("summary", title)
        description_parts = [f"Type: {kind}"]
        if document_name:
            description_parts.append(f"Source: {document_name}")
        if confidence is not None:
            description_parts.append(f"Confidence: {float(confidence):.0%}")
        if source_text:
            description_parts.append(f"Clause: {source_text[:300]}")
        description_parts.append("Created by LifePilot")
        event.add("description", "\n".join(description_parts))
        event.add("categories", [kind, "LifePilot"])
        event.add("transp", "OPAQUE")
        event.add("status", "CONFIRMED")

        if include_alarms:
            remind_days = _field(item, "remind_days_before", 7) or 7
            reminder_date = due_date - timedelta(days=max(1, int(remind_days)))
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", f"Reminder: {title}")
            alarm.add("trigger", datetime.combine(reminder_date, time(9, 0)).replace(tzinfo=timezone.utc))
            event.add_component(alarm)

        calendar.add_component(event)

    return calendar.to_ical()


def build_document_calendar(deadlines: Sequence[Any], *, document_name: str) -> bytes:
    """Calendar export scoped to one document."""
    return build_calendar(
        deadlines,
        calendar_name=f"LifePilot - {document_name}",
    )
