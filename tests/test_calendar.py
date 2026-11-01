"""iCalendar export tests."""

from __future__ import annotations

from datetime import date

from icalendar import Calendar

from lifepilot.exports.calendar import build_calendar, build_document_calendar


def deadline_rows() -> list[dict]:
    return [
        {
            "id": 1,
            "title": "Pay electricity bill",
            "due_date": date(2026, 11, 6),
            "kind": "payment",
            "confidence": 0.93,
            "remind_days_before": 3,
            "document_name": "electricity_bill.pdf",
            "source_text": "Pay by 06/11/2026",
        },
        {
            "id": 2,
            "title": "Warranty expires",
            "due_date": date(2028, 8, 11),
            "kind": "expiry",
            "confidence": 0.85,
            "remind_days_before": 30,
            "document_name": "warranty_card.pdf",
        },
    ]


def test_calendar_contains_events_and_alarms() -> None:
    raw = build_calendar(deadline_rows())
    assert isinstance(raw, bytes)
    calendar = Calendar.from_ical(raw)
    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    assert len(events) == 2
    summaries = {str(event.get("summary")) for event in events}
    assert summaries == {"Pay electricity bill", "Warranty expires"}
    first = next(event for event in events if "Pay" in str(event.get("summary")))
    assert first.decoded("dtstart") == date(2026, 11, 6)
    alarms = [component for component in first.walk() if component.name == "VALARM"]
    assert len(alarms) == 1
    assert "electricity_bill.pdf" in str(first.get("description"))


def test_document_calendar_has_custom_name() -> None:
    raw = build_document_calendar(deadline_rows()[:1], document_name="bill.pdf")
    calendar = Calendar.from_ical(raw)
    assert "bill.pdf" in str(calendar.get("x-wr-calname"))
    assert len([item for item in calendar.walk() if item.name == "VEVENT"]) == 1


def test_empty_calendar_is_still_valid() -> None:
    calendar = Calendar.from_ical(build_calendar([]))
    assert calendar.get("version") == "2.0"
    assert not [item for item in calendar.walk() if item.name == "VEVENT"]
