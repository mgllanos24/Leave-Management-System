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


def _require_env(key: str) -> str:
    """Return the value of ``key`` from the environment or raise an error."""

    value = os.getenv(key)
    if value is None or value.strip() == "":
        raise RuntimeError(
            f"{key} environment variable is required for SMTP email delivery"
        )
    return value


# Configuration must be supplied via the environment to avoid shipping secrets
# in source control. A clear error is raised during application startup when the
# variables are missing so deployments can fail fast.
SMTP_SERVER = _require_env("SMTP_SERVER")
try:
    SMTP_PORT = int(_require_env("SMTP_PORT"))
except ValueError as exc:  # pragma: no cover - defensive
    raise RuntimeError("SMTP_PORT must be an integer") from exc
SMTP_USERNAME = _require_env("SMTP_USERNAME")
SMTP_PASSWORD = _require_env("SMTP_PASSWORD")

# Calendar time entries should be interpreted in local business time instead
# of UTC to avoid clients shifting request hours into the prior/next day.
CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "America/Los_Angeles")


def generate_ics_content(
    start_date: str,
    end_date: str,
    summary: str,
    description: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
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
    ]

    if start_time or end_time:
        start_clock = start_time or "00:00"
        end_clock = end_time or start_clock
        start_dt = datetime.fromisoformat(f"{start_date}T{start_clock}")
        end_dt = datetime.fromisoformat(f"{end_date}T{end_clock}")
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)
        lines.append(f"DTSTART;TZID={CALENDAR_TIMEZONE}:{start_dt.strftime('%Y%m%dT%H%M%S')}")
        lines.append(f"DTEND;TZID={CALENDAR_TIMEZONE}:{end_dt.strftime('%Y%m%dT%H%M%S')}")
    else:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
        lines.append(f"DTSTART;VALUE=DATE:{start_dt.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{end_dt.strftime('%Y%m%d')}")

    lines.append(f"SUMMARY:{summary}")

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
            msg.add_alternative(
                ics_content,
                subtype="calendar",
                params={"method": "REQUEST"},
            )
            msg["Content-Class"] = "urn:content-classes:calendarmessage"

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
