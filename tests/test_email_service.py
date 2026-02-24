import importlib
import os
from datetime import datetime

import pytest

for key, value in (
    ("SMTP_SERVER", "smtp.test"),
    ("SMTP_PORT", "2525"),
    ("SMTP_USERNAME", "user@test"),
    ("SMTP_PASSWORD", "secret"),
):
    os.environ.setdefault(key, value)

from services import email_service


def test_calendar_timezone_defaults_to_los_angeles(monkeypatch):
    monkeypatch.delenv("CALENDAR_TIMEZONE", raising=False)
    importlib.reload(email_service)

    assert email_service.CALENDAR_TIMEZONE == "America/Los_Angeles"


def test_send_notification_email_inlines_ics(monkeypatch):
    captured = {}

    class DummySMTP:
        def __init__(self, server, port):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def starttls(self):
            pass

        def login(self, username, password):
            pass

        def send_message(self, msg):
            captured["msg"] = msg

    monkeypatch.setattr(email_service.smtplib, "SMTP", DummySMTP)

    ok, err = email_service.send_notification_email(
        to_addr="test@example.com",
        subject="Test",
        body="Body",
        ics_content="BEGIN:VCALENDAR\r\nEND:VCALENDAR",
    )

    assert ok and err is None
    msg = captured["msg"]
    calendar_part = msg.get_body(("calendar",))
    assert calendar_part is not None
    assert calendar_part.get_content_type() == "text/calendar"
    assert list(msg.iter_attachments()) == []
    assert msg["Content-Class"] == "urn:content-classes:calendarmessage"


def test_generate_ics_content_uses_tzid_and_never_utc(monkeypatch):
    monkeypatch.setattr(email_service, "CALENDAR_TIMEZONE", "America/Los_Angeles")

    ics = email_service.generate_ics_content(
        start_date="2026-03-13",
        end_date="2026-03-16",
        summary="Mark Llanos - Personal Leave",
        description="Return Date: 2026-03-17",
        start_time="06:30",
        end_time="15:00",
        uid="APP-123@leave-management-system",
        organizer_email="organizer@example.com",
        organizer_name="Leave Bot",
        attendee_email="employee@example.com",
        attendee_name="Employee Name",
        sequence=2,
        status="CONFIRMED",
    )

    assert "METHOD:REQUEST" in ics
    assert "BEGIN:VTIMEZONE" in ics
    assert "TZID:America/Los_Angeles" in ics
    assert "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU" in ics
    assert "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU" in ics
    assert "DTSTART;TZID=America/Los_Angeles:20260313T063000" in ics
    assert "DTEND;TZID=America/Los_Angeles:20260316T150000" in ics
    assert "DTSTART:20260313" not in ics
    assert "DTEND:20260316" not in ics
    dt_lines = [line for line in ics.splitlines() if line.startswith(("DTSTART", "DTEND"))]
    assert all(not line.endswith("Z") for line in dt_lines)


def test_generate_leave_event_ics_validates_inputs():
    with pytest.raises(ValueError, match="employee_name"):
        email_service.generate_leave_event_ics(
            employee_name=" ",
            start_local=datetime(2026, 3, 13, 6, 30),
            end_local=datetime(2026, 3, 16, 15, 0),
        )

    with pytest.raises(ValueError, match="must be after"):
        email_service.generate_leave_event_ics(
            employee_name="Mark",
            start_local=datetime(2026, 3, 16, 15, 0),
            end_local=datetime(2026, 3, 13, 6, 30),
        )


def test_generate_leave_event_ics_outlook_safe_example():
    ics = email_service.generate_leave_event_ics(
        employee_name="Mark Llanos",
        start_local=datetime(2026, 3, 13, 6, 30),
        end_local=datetime(2026, 3, 16, 15, 0),
        tzid="America/Los_Angeles",
        uid="APP-20260223-98D82C78@leave-management-system",
        summary="Mark Llanos - Personal Leave",
        description="Return Date: 2026-03-17",
    )

    assert "UID:APP-20260223-98D82C78@leave-management-system" in ics
    assert "DTSTAMP:" in ics
    assert "DTSTART;TZID=America/Los_Angeles:20260313T063000" in ics
    assert "DTEND;TZID=America/Los_Angeles:20260316T150000" in ics
    assert "DESCRIPTION:Return Date: 2026-03-17" in ics
