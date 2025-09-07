"""
Service: Email Service. Purpose: Send notifications and alerts via SMTP.
"""

import logging
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
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "qtaskvacation@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "bicg llyb myff kigu")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")


logger = logging.getLogger(__name__)

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

    # Fall back to module level constants or environment variables only when
    # no explicit credentials were supplied. Empty strings are allowed to
    # deliberately disable authentication.
    if username is None:
        username = SMTP_USERNAME
    if password is None:
        password = SMTP_PASSWORD

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
            if username and password:
                try:
                    s.login(username, password)
                except smtplib.SMTPAuthenticationError:
                    logger.exception("SMTP authentication failed")
                    return False
            s.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 - broad exception to log any failure
        logger.exception("Email sending failed")
        return False


def _todo():
    """Placeholder to keep the module importable."""
    return None

