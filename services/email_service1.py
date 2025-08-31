"""
Service: Email Service. Purpose: Send notifications and alerts via SMTP.
TODO: implement functions and add error handling.
"""
import os
import smtplib
from email.message import EmailMessage

def send_notification_email(to_addr: str, subject: str, body: str,
                            SMTP_SERVER = "smtp.gmail.com", 
                            SMTP_PORT = 587,
                            username=None, password=None) -> bool:
    """Send notification email via SMTP with configurable settings."""
    SMTP_USERNAME = "qtaskvacation@gmail.com"
    SMTP_PASSWORD = "bicg llyb myff kigu"
    if not (username and password):
        return False
    
    msg = EmailMessage()
    msg["From"] = username
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as s:
            s.starttls()
            s.login(username, password)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"Email sending failed: {e}")
        return False

def _todo():
    """Placeholder to keep the module importable."""
    return None