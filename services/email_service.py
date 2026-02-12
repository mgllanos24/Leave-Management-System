"""Email service for sending notifications via SMTP.

Supports plain text and HTML messages, optional iCalendar attachments, and
configuration through environment variables. Future enhancements may include
templating or asynchronous delivery.
"""

import logging
import os
import smtplib
import uuid
from datetime import UTC, datetime, timedelta, tzinfo
from email.message import EmailMessage
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
# Default timezone is set to Pacific time (Anaheim) unless overridden by
# CALENDAR_TIMEZONE in the environment.
CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "America/Los_Angeles")
CALENDAR_FORCE_UTC = os.getenv("CALENDAR_FORCE_UTC", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _format_ics_datetime(dt: datetime) -> str:
    """Return datetime in ICS basic format without separators."""

    return dt.strftime("%Y%m%dT%H%M%S")


def _format_utc_offset(offset: timedelta) -> str:
    """Format UTC offset timedelta into ICS TZOFFSET (+/-HHMM)."""

    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours:02d}{minutes:02d}"


def _build_vtimezone_block(tzid: str) -> list[str]:
    """Create a VTIMEZONE block for the configured TZID.

    The block uses current-year transitions for the timezone. This improves
    compatibility with clients that require explicit timezone declarations.
    """

    zone = ZoneInfo(tzid)
    year = datetime.now(UTC).year
    day = datetime(year, 1, 1)
    one_day = timedelta(days=1)
    transitions: list[tuple[datetime, timedelta, timedelta]] = []
    previous_offset = day.replace(tzinfo=zone).utcoffset()

    # Scan the year to detect offset changes (DST boundaries).
    while day.year == year:
        current_offset = day.replace(tzinfo=zone).utcoffset()
        if current_offset != previous_offset:
            transitions.append((day, previous_offset, current_offset))
            previous_offset = current_offset
        day += one_day

    lines = [
        "BEGIN:VTIMEZONE",
        f"TZID:{tzid}",
        f"X-LIC-LOCATION:{tzid}",
    ]

    if not transitions:
        # Fixed-offset timezone without DST changes.
        offset = datetime(year, 1, 1, tzinfo=zone).strftime("%z")
        lines.extend(
            [
                "BEGIN:STANDARD",
                f"DTSTART:{year}0101T000000",
                f"TZOFFSETFROM:{offset}",
                f"TZOFFSETTO:{offset}",
                "END:STANDARD",
            ]
        )
    else:
        for transition_date, offset_from, offset_to in transitions:
            section = "DAYLIGHT" if offset_to > offset_from else "STANDARD"
            lines.extend(
                [
                    f"BEGIN:{section}",
                    f"DTSTART:{transition_date.strftime('%Y%m%dT020000')}",
                    f"TZOFFSETFROM:{_format_utc_offset(offset_from)}",
                    f"TZOFFSETTO:{_format_utc_offset(offset_to)}",
                    f"TZNAME:{transition_date.replace(tzinfo=zone).tzname() or tzid}",
                    f"END:{section}",
                ]
            )

    lines.append("END:VTIMEZONE")
    return lines


def generate_ics_content(
    start_date: str,
    end_date: str,
    summary: str,
    description: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    uid: str | None = None,
    organizer_email: str | None = None,
    organizer_name: str | None = None,
    attendee_email: str | None = None,
    attendee_name: str | None = None,
    sequence: int = 0,
    status: str = "CONFIRMED",
    force_utc: bool = CALENDAR_FORCE_UTC,
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

    uid = uid or f"{uuid.uuid4()}@leave-management-system"
    dtstamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Leave Management System//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
    ]

    effective_force_utc = force_utc
    calendar_zone: tzinfo | None = None

<<<<<<< codex/fix-calendar-date-display-wv98xz
    if (start_time or end_time) and not force_utc:
        try:
            lines.extend(_build_vtimezone_block(CALENDAR_TIMEZONE))
        except ZoneInfoNotFoundError:
            logging.warning(
                "CALENDAR_TIMEZONE '%s' is unavailable; emitting TZID entries without VTIMEZONE",
                CALENDAR_TIMEZONE,
            )

=======
>>>>>>> main
    lines.extend([
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
    ])

    if start_time or end_time:
        start_clock = start_time or "00:00"
        end_clock = end_time or start_clock
        start_dt = datetime.fromisoformat(f"{start_date}T{start_clock}")
        end_dt = datetime.fromisoformat(f"{end_date}T{end_clock}")
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)
        if effective_force_utc:
            utc_zone = UTC
            if calendar_zone is None:
                try:
                    calendar_zone = ZoneInfo(CALENDAR_TIMEZONE)
                except ZoneInfoNotFoundError:
                    calendar_zone = utc_zone
            start_utc = start_dt.replace(tzinfo=calendar_zone).astimezone(utc_zone)
            end_utc = end_dt.replace(tzinfo=calendar_zone).astimezone(utc_zone)
            lines.append(f"DTSTART:{_format_ics_datetime(start_utc)}Z")
            lines.append(f"DTEND:{_format_ics_datetime(end_utc)}Z")
        else:
            # Use floating local times so calendar clients preserve exact hours
            # entered in the leave request without timezone shifts.
            lines.append(f"DTSTART:{_format_ics_datetime(start_dt)}")
            lines.append(f"DTEND:{_format_ics_datetime(end_dt)}")
    else:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
        lines.append(f"DTSTART;VALUE=DATE:{start_dt.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{end_dt.strftime('%Y%m%d')}")

    lines.append(f"SUMMARY:{summary}")
    lines.append(f"SEQUENCE:{sequence}")
    lines.append(f"STATUS:{status}")

    if organizer_email:
        organizer_cn = organizer_name or organizer_email
        lines.append(f"ORGANIZER;CN={organizer_cn}:mailto:{organizer_email}")

    if attendee_email:
        attendee_cn = attendee_name or attendee_email
        lines.append(
            "ATTENDEE;CN="
            f"{attendee_cn};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:"
            f"mailto:{attendee_email}"
        )

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
