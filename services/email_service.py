"""Email service for sending notifications via SMTP.

Supports plain text and HTML messages, optional iCalendar attachments, and
configuration through environment variables.
"""

import logging
import os
import smtplib
import uuid
from datetime import UTC, datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _require_env(key: str) -> str:
    """Return required env var value or raise a startup error."""

    value = os.getenv(key)
    if value is None or value.strip() == "":
        raise RuntimeError(
            f"{key} environment variable is required for SMTP email delivery"
        )
    return value


SMTP_SERVER = _require_env("SMTP_SERVER")
try:
    SMTP_PORT = int(_require_env("SMTP_PORT"))
except ValueError as exc:  # pragma: no cover
    raise RuntimeError("SMTP_PORT must be an integer") from exc
SMTP_USERNAME = _require_env("SMTP_USERNAME")
SMTP_PASSWORD = _require_env("SMTP_PASSWORD")

CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "America/Los_Angeles")
CALENDAR_FORCE_UTC = os.getenv("CALENDAR_FORCE_UTC", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CALENDAR_UTC_OFFSET_HOURS = int(os.getenv("CALENDAR_UTC_OFFSET_HOURS", "-8"))


def _format_ics_datetime(dt: datetime) -> str:
    """Return datetime in ICS basic format without separators."""

    return dt.strftime("%Y%m%dT%H%M%S")


def _format_utc_offset(offset: timedelta) -> str:
    """Return +HHMM/-HHMM from a timedelta offset."""

    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"{sign}{hours:02d}{minutes:02d}"


def _build_vtimezone_block(tzid: str, years: set[int]) -> list[str]:
    """Create VTIMEZONE rules for transition years touched by an event."""

    zone = ZoneInfo(tzid)
    sorted_years = sorted(years)
    day = datetime(sorted_years[0], 1, 1)
    end_day = datetime(sorted_years[-1] + 1, 1, 1)
    one_day = timedelta(days=1)

    transitions: list[tuple[datetime, timedelta, timedelta]] = []
    previous_offset = day.replace(hour=12, tzinfo=zone).utcoffset()

    while day < end_day:
        current_offset = day.replace(hour=12, tzinfo=zone).utcoffset()
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
        offset = datetime(sorted_years[0], 1, 1, tzinfo=zone).utcoffset() or timedelta(0)
        offset_str = _format_utc_offset(offset)
        lines.extend(
            [
                "BEGIN:STANDARD",
                f"DTSTART:{sorted_years[0]}0101T000000",
                f"TZOFFSETFROM:{offset_str}",
                f"TZOFFSETTO:{offset_str}",
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
    floating_time: bool = False,
) -> str:
    """Create an ICS calendar event payload."""

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
        start_clock = start_time or "00:00"
        end_clock = end_time or start_clock
        start_dt = datetime.fromisoformat(f"{start_date}T{start_clock}")
        end_dt = datetime.fromisoformat(f"{end_date}T{end_clock}")
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)

        if force_utc:
            local_zone = ZoneInfo(CALENDAR_TIMEZONE)
            start_utc = start_dt.replace(tzinfo=local_zone).astimezone(UTC)
            end_utc = end_dt.replace(tzinfo=local_zone).astimezone(UTC)
            dtstart_line = f"DTSTART:{_format_ics_datetime(start_utc)}Z"
            dtend_line = f"DTEND:{_format_ics_datetime(end_utc)}Z"
        elif floating_time:
            dtstart_line = f"DTSTART:{_format_ics_datetime(start_dt)}"
            dtend_line = f"DTEND:{_format_ics_datetime(end_dt)}"
        else:
            try:
                _ = ZoneInfo(CALENDAR_TIMEZONE)
                years = {start_dt.year, end_dt.year}
                lines.extend(_build_vtimezone_block(CALENDAR_TIMEZONE, years))
                dtstart_line = (
                    f"DTSTART;TZID={CALENDAR_TIMEZONE}:{_format_ics_datetime(start_dt)}"
                )
                dtend_line = (
                    f"DTEND;TZID={CALENDAR_TIMEZONE}:{_format_ics_datetime(end_dt)}"
                )
            except ZoneInfoNotFoundError:
                logging.warning(
                    "Unable to resolve CALENDAR_TIMEZONE=%s; using floating local times",
                    CALENDAR_TIMEZONE,
                )
                _fallback_zone = timezone(timedelta(hours=CALENDAR_UTC_OFFSET_HOURS))
                dtstart_line = f"DTSTART:{_format_ics_datetime(start_dt)}"
                dtend_line = f"DTEND:{_format_ics_datetime(end_dt)}"

        lines.extend(["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{dtstamp}", dtstart_line, dtend_line])
    else:
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{dtstamp}",
                f"DTSTART;VALUE=DATE:{start_dt.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{end_dt.strftime('%Y%m%d')}",
            ]
        )

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
    """Send notification email via SMTP with configurable settings."""

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

        with smtplib.SMTP(smtp_server, smtp_port) as s:
            s.starttls()
            s.login(username, password)
            s.send_message(msg)
        return True, None
    except Exception as e:  # noqa: BLE001
        logging.exception(
            "Email sending failed to %s with subject %s: %s", to_addr, subject, e
        )
        return False, str(e)
