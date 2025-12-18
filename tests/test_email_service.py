import os

for key, value in (
    ("SMTP_SERVER", "smtp.test"),
    ("SMTP_PORT", "2525"),
    ("SMTP_USERNAME", "user@test"),
    ("SMTP_PASSWORD", "secret"),
):
    os.environ.setdefault(key, value)

from services import email_service


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
            captured['msg'] = msg

    monkeypatch.setattr(email_service.smtplib, "SMTP", DummySMTP)

    ok, err = email_service.send_notification_email(
        to_addr="test@example.com",
        subject="Test", 
        body="Body",
        ics_content="BEGIN:VCALENDAR\r\nEND:VCALENDAR",
    )

    assert ok and err is None
    msg = captured['msg']
    # Should have an inline text/calendar part
    calendar_part = msg.get_body(("calendar",))
    assert calendar_part is not None
    assert calendar_part.get_content_type() == "text/calendar"
    # No attachments expected
    assert list(msg.iter_attachments()) == []
    # Optional header for compatibility
    assert msg["Content-Class"] == "urn:content-classes:calendarmessage"


def test_generate_ics_content_respects_timezone(monkeypatch):
    monkeypatch.setenv("CALENDAR_TIMEZONE", "America/Los_Angeles")

    ics = email_service.generate_ics_content(
        start_date="2026-01-16",
        end_date="2026-01-30",
        summary="Test",
        description=None,
        start_time="06:30",
        end_time="15:00",
    )

    assert "DTSTART:20260116T143000Z" in ics
    assert "DTEND:20260130T230000Z" in ics
