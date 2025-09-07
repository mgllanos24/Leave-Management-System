"""Email service for sending notifications via SMTP.

Supports plain text and HTML messages, optional iCalendar attachments, and
configuration through environment variables. Future enhancements may include
templating or asynchronous delivery.
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
        "METHOD:REQUEST",
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
    html_body: str | None = None,
) -> tuple[bool, str | None]:
    """Send notification email via SMTP with configurable settings.

    Parameters
    ----------
    to_addr, subject, body:
        Standard email fields. ``body`` is used as the plain text version.
    html_body:
        Optional HTML version of the message. If provided the message will be
        sent as a multipart/alternative email containing both plain text and
        HTML parts.
    ics_content:
        Optional iCalendar content to attach as ``event.ics`` for calendar
        integration.

    Returns
    -------
    tuple[bool, str | None]
        ``True`` and ``None`` if the email was sent successfully. Otherwise,
        ``False`` and the string representation of the exception raised.
    """

    # Fall back to module level constants or environment variables if explicit
    # credentials were not supplied.
    username = username or SMTP_USERNAME
    password = password or SMTP_PASSWORD

    try:
        msg = EmailMessage()
        msg["From"] = username or ""
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)

        if html_body:
            msg.add_alternative(html_body, subtype="html")

        if ics_content:
            msg.add_attachment(
                ics_content,
                subtype="calendar",
                filename="event.ics",
                params={"method": "REQUEST"},
            )

        logging.debug(
            "Sending email to %s with subject %s; ICS attached: %s",
            to_addr,
            subject,
            bool(ics_content),
        )

        with smtplib.SMTP(smtp_server, smtp_port) as s:
            s.starttls()
            s.login(username, password)
            s.send_message(msg)
        return True, None
    except Exception as e:  # noqa: BLE001 - broad exception to log any failure
        logging.exception(
            "Email sending failed to %s with subject %s: %s", to_addr, subject, e
        )
        return False, str(e)
