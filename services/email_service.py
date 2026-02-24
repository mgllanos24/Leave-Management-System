"""Email service for sending notifications via SMTP.

Supports plain text and HTML messages, optional iCalendar attachments, and
configuration through environment variables. Future enhancements may include
templating or asynchronous delivery.
"""

import logging
import os
import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo


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
def _format_ics_datetime(dt: datetime) -> str:
    """Return datetime in ICS basic format without separators."""

    return dt.strftime("%Y%m%dT%H%M%S")


def _build_vtimezone_block(tzid: str) -> list[str]:
    """Return an Outlook-friendly RRULE-based VTIMEZONE block."""

    if tzid != "America/Los_Angeles":
        raise ValueError(f"Unsupported tzid for leave events: {tzid}")

    return [
        "BEGIN:VTIMEZONE",
        "TZID:America/Los_Angeles",
        "X-LIC-LOCATION:America/Los_Angeles",
        "BEGIN:DAYLIGHT",
        "TZOFFSETFROM:-0800",
        "TZOFFSETTO:-0700",
        "TZNAME:PDT",
        "DTSTART:19700308T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:-0700",
        "TZOFFSETTO:-0800",
        "TZNAME:PST",
        "DTSTART:19701101T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

def _build_vtimezone_block(tzid: str, years: set[int]) -> list[str]:
    """Create a VTIMEZONE block for the configured TZID.

    The block uses the provided event years so transitions match invites that
    are generated ahead of time.
    """

    zone = ZoneInfo(tzid)
    sorted_years = sorted(years)
    day = datetime(sorted_years[0], 1, 1)
    end_day = datetime(sorted_years[-1] + 1, 1, 1)
    one_day = timedelta(days=1)
    transitions: list[tuple[datetime, timedelta, timedelta]] = []
    # Use midday offsets to avoid detecting DST changes one day late.
    previous_offset = day.replace(hour=12, tzinfo=zone).utcoffset()

    # Scan the requested years to detect offset changes (DST boundaries).
    while day < end_day:
        current_offset = day.replace(hour=12, tzinfo=zone).utcoffset()
        if current_offset != previous_offset:
            transitions.append((day, previous_offset, current_offset))
            previous_offset = current_offset
        day += one_day

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Leave Management System//EN",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        *_build_vtimezone_block(tzid),
        "BEGIN:VEVENT",
        f"UID:{event_uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;TZID={tzid}:{_format_ics_datetime(start_local)}",
        f"DTEND;TZID={tzid}:{_format_ics_datetime(end_local)}",
        f"SUMMARY:{event_summary}",
        f"DESCRIPTION:{event_description}",
    ]

    if not transitions:
        # Fixed-offset timezone without DST changes.
        offset = datetime(sorted_years[0], 1, 1, tzinfo=zone).strftime("%z")
        lines.extend(
            [
                "BEGIN:STANDARD",
                f"DTSTART:{sorted_years[0]}0101T000000",
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

    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


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
    floating_time: bool = False,
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

    if start_time or end_time:
        try:
            calendar_zone = ZoneInfo(CALENDAR_TIMEZONE)
        except ZoneInfoNotFoundError:
            logging.warning(
                "Unable to resolve CALENDAR_TIMEZONE=%s; falling back to fixed UTC offset",
                CALENDAR_TIMEZONE,
            )
            calendar_zone = timezone(timedelta(hours=CALENDAR_UTC_OFFSET_HOURS))

        # Include explicit timezone data for local-time invites so clients can
        # correctly handle DST transitions, unless floating local time was
        # explicitly requested.
        using_named_timezone = (
            not floating_time
            and getattr(calendar_zone, "key", None) == CALENDAR_TIMEZONE
        )
        if not effective_force_utc and using_named_timezone:
            years = {
                datetime.fromisoformat(start_date).year,
                datetime.fromisoformat(end_date).year,
            }
            lines.extend(_build_vtimezone_block(CALENDAR_TIMEZONE, years))

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
        lines.append(f"DTSTART;TZID={CALENDAR_TIMEZONE}:{_format_ics_datetime(start_dt)}")
        lines.append(f"DTEND;TZID={CALENDAR_TIMEZONE}:{_format_ics_datetime(end_dt)}")
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


def _demo_leave_ics_output() -> None:
    """Print an example leave ICS and key lines for quick verification."""

    ics = generate_leave_event_ics(
        employee_name="Mark Llanos",
        start_local=datetime(2026, 3, 13, 6, 30),
        end_local=datetime(2026, 3, 16, 15, 0),
        uid="APP-20260223-98D82C78@leave-management-system",
        summary="Mark Llanos - Personal Leave",
        description="Return Date: 2026-03-17",
    )
    print(ics)
    print("\n--- Key lines ---")
    for line in ics.splitlines():
        if line.startswith(("DTSTART", "DTEND", "BEGIN:VTIMEZONE", "TZID:")):
            print(line)


if __name__ == "__main__":
    _demo_leave_ics_output()


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
