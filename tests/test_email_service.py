import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from services import email_service
from server import format_leave_decision_email, next_workday


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


def test_decision_notifications_include_return_date():
    holidays = {"2023-07-04"}
    return_date = next_workday("2023-07-03", holidays)
    admin_body = format_leave_decision_email(
        "admin",
        "Alice",
        "APP-1",
        "Annual",
        "2023-07-01",
        "2023-07-03",
        1,
        return_date,
        "approved",
    )
    employee_body = format_leave_decision_email(
        "employee",
        "Alice",
        "APP-1",
        "Annual",
        "2023-07-01",
        "2023-07-03",
        1,
        return_date,
        "approved",
    )
    assert return_date in admin_body
    assert return_date in employee_body
