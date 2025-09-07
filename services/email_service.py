"""
Service: Email Service. Purpose: Send notifications and alerts via SMTP.
"""

import os
import smtplib
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage


# Default configuration can be provided via environment variables. These values
# are only used if explicit settings are not supplied when calling
# ``send_notification_email``.
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

missing_creds = []
if not SMTP_USERNAME:
    missing_creds.append("SMTP_USERNAME")
if not SMTP_PASSWORD:
    missing_creds.append("SMTP_PASSWORD")
if missing_creds:
    raise RuntimeError(
        "Missing required environment variable(s): " + ", ".join(missing_creds)
    )
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")


def _sanitize_ics_text(value: str) -> str:
    """Escape characters that can break ICS formatting.

    Per RFC 5545, text values must escape carriage returns, line feeds, and
    commas. Newlines are converted to the escaped ``\n`` sequence and commas
    are escaped with a leading backslash.
    """

    # Normalize different newline representations then escape them and commas.
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\n", "\\n")
    value = value.replace(",", "\\,")
    return value


def generate_ics_content(
    start_date: str,
    end_date: str,
    summary: str,
    description: str | None = None,
) -> str:
    """Create a basic ICS calendar event.

    Parameters
    ----------
    start_date, end_date:
        Dates in ISO ``YYYY-MM-DD`` format. ``end_date`` is treated as
        inclusive and will be incremented by one day for the ICS ``DTEND``
        field which is exclusive.
    summary:
        Event title shown on the calendar entry.
    description:
        Optional description to include with the event.
    """

    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
    uid = f"{uuid.uuid4()}@leave-management-system"
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    summary = _sanitize_ics_text(summary)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Leave Management System//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{start_dt.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{end_dt.strftime('%Y%m%d')}",
        f"SUMMARY:{summary}",
    ]

    if description:
        description = _sanitize_ics_text(description)
        lines.append(f"DESCRIPTION:{description}")

    lines.extend(["END:VEVENT", "END:VCALENDAR"])

    return "\r\n".join(lines)


def send_notification_email(
    to_addr: str,
    subject: str,
    body: str,
    smtp_server: str = SMTP_SERVER,
    smtp_port: int = SMTP_PORT,
    username: str | None = None,
    password: str | None = None,
    ics_content: str | None = None,
) -> bool:
    """Send notification email via SMTP with configurable settings."""

    # Fall back to module level constants or environment variables if explicit
    # credentials were not supplied.
    username = username or SMTP_USERNAME
    password = password or SMTP_PASSWORD

    msg = EmailMessage()
    msg["From"] = username or ""
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    if ics_content:
        msg.add_attachment(
            ics_content,
            maintype="text",
            subtype="calendar",
            filename="event.ics",
        )

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as s:
            s.starttls()
            s.login(username, password)
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 - broad exception to log any failure
        print(f"Email sending failed: {e}")
        return False


def _todo():
    """Placeholder to keep the module importable."""
    return None

