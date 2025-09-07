import smtplib
from email.message import EmailMessage
from pathlib import Path
import sys

import pytest

# Ensure the project root is on the import path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.email_service import generate_ics_content, send_notification_email


def test_generate_ics_includes_method_request():
    ics = generate_ics_content("2024-01-01", "2024-01-02", "Vacation")
    assert "METHOD:REQUEST" in ics


def test_send_notification_email_sets_invite_headers(monkeypatch):
    sent_msg: EmailMessage | None = None

    class DummySMTP:
        def __init__(self, *args, **kwargs):
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
            nonlocal sent_msg
            sent_msg = msg

    monkeypatch.setattr(smtplib, "SMTP", DummySMTP)

    ics = generate_ics_content("2024-01-01", "2024-01-02", "Vacation")
    assert send_notification_email("to@example.com", "Subject", "Body", ics_content=ics)

    assert sent_msg is not None
    attachments = list(sent_msg.iter_attachments())
    assert len(attachments) == 1
    attachment = attachments[0]
    # Content-Type should include method=REQUEST so email clients treat it as invite
    content_type = attachment.get("Content-Type")
    assert content_type is not None
    assert "method=\"REQUEST\"" in content_type
    # Custom header used by some clients
    assert attachment["Content-Class"] == "urn:content-classes:calendarmessage"
