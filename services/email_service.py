"""
Service: Email Service. Purpose: Send notifications and alerts via SMTP.
"""

import os
import smtplib
from email.message import EmailMessage


# Default configuration can be provided via environment variables. These values
# are only used if explicit settings are not supplied when calling
# ``send_notification_email``.
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "qtaskvacation@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "bicg llyb myff kigu")


def send_notification_email(
    to_addr: str,
    subject: str,
    body: str,
    smtp_server: str = SMTP_SERVER,
    smtp_port: int = SMTP_PORT,
    username: str | None = None,
    password: str | None = None,
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

