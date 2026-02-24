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
    assert "DTSTART;TZID=America/Los_Angeles:20260210T063000" in ics
    assert "DTEND;TZID=America/Los_Angeles:20260210T150000" in ics
    assert "UID:APP-123@leave-management-system" in ics
    assert "ORGANIZER;CN=Leave Bot:mailto:organizer@example.com" in ics
    assert "ATTENDEE;CN=Employee Name;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:employee@example.com" in ics
    assert "SEQUENCE:2" in ics
    assert "STATUS:CONFIRMED" in ics




def test_generate_ics_content_can_emit_floating_times_without_timezone(monkeypatch):
    monkeypatch.setattr(email_service, "CALENDAR_TIMEZONE", "America/Los_Angeles")

    ics = email_service.generate_ics_content(
        start_date="2026-03-07",
        end_date="2026-03-09",
        summary="Floating local time",
        start_time="06:30",
        end_time="15:00",
        force_utc=False,
        floating_time=True,
    )

    assert "BEGIN:VTIMEZONE" not in ics
    assert "DTSTART;TZID=" not in ics
    assert "DTEND;TZID=" not in ics
    assert "DTSTART:20260307T063000" in ics
    assert "DTEND:20260309T150000" in ics

def test_generate_ics_content_can_emit_utc(monkeypatch):
    monkeypatch.setattr(email_service, "CALENDAR_TIMEZONE", "America/Los_Angeles")

    ics = email_service.generate_ics_content(
        start_date="2026-02-10",
        end_date="2026-02-10",
        summary="Eduardo Orozco - OOO",
        start_time="06:30",
        end_time="15:00",
        force_utc=True,
    )

    assert "BEGIN:VTIMEZONE" not in ics
    assert "DTSTART:20260210T143000Z" in ics
    assert "DTEND:20260210T230000Z" in ics


def test_generate_ics_content_with_local_times_falls_back_without_zoneinfo(monkeypatch):
    monkeypatch.setattr(email_service, "CALENDAR_TIMEZONE", "America/Los_Angeles")

    def fake_zone_info(key):
        raise email_service.ZoneInfoNotFoundError("missing tzdata")

    monkeypatch.setattr(email_service, "ZoneInfo", fake_zone_info)

    ics = email_service.generate_ics_content(
        start_date="2026-02-10",
        end_date="2026-02-10",
        summary="Timezone fallback",
        start_time="06:30",
        end_time="15:00",
    )

    assert "BEGIN:VTIMEZONE" not in ics
    assert "DTSTART:20260210T063000" in ics
    assert "DTEND:20260210T150000" in ics


def test_generate_ics_content_uses_datetime_utc_without_zoneinfo_lookup(monkeypatch):
    monkeypatch.setattr(email_service, "CALENDAR_TIMEZONE", "America/Los_Angeles")

    real_zone_info = email_service.ZoneInfo

    def fake_zone_info(key):
        if key == "UTC":
            raise AssertionError("UTC should not be resolved via ZoneInfo")
        return real_zone_info(key)

    monkeypatch.setattr(email_service, "ZoneInfo", fake_zone_info)

    ics = email_service.generate_ics_content(
        start_date="2026-02-10",
        end_date="2026-02-10",
        summary="UTC fallback",
        start_time="06:30",
        end_time="15:00",
        force_utc=True,
    )

    assert "DTSTART:20260210T143000Z" in ics
    assert "DTEND:20260210T230000Z" in ics


def test_generate_ics_content_utc_conversion_honors_dst(monkeypatch):
    monkeypatch.setattr(email_service, "CALENDAR_TIMEZONE", "America/Los_Angeles")

    ics = email_service.generate_ics_content(
        start_date="2026-06-10",
        end_date="2026-06-10",
        summary="DST check",
        start_time="06:30",
        end_time="15:00",
        force_utc=True,
    )

    # June in Los Angeles should use daylight time (UTC-07:00).
    assert "DTSTART:20260610T133000Z" in ics
    assert "DTEND:20260610T220000Z" in ics


def test_generate_ics_content_vtimezone_uses_event_year_transitions(monkeypatch):
    monkeypatch.setattr(email_service, "CALENDAR_TIMEZONE", "America/Los_Angeles")

    ics = email_service.generate_ics_content(
        start_date="2026-03-13",
        end_date="2026-03-13",
        summary="Event with timezone block",
        start_time="06:30",
        end_time="15:00",
    )

    assert "BEGIN:DAYLIGHT" in ics
    assert "DTSTART:20260308T020000" in ics
    assert "BEGIN:STANDARD" in ics
    assert "DTSTART:20261101T020000" in ics
