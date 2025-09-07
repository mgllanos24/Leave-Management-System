"""Service: Leave Service. Handle leave applications and approvals."""
from __future__ import annotations

from typing import Optional

from .database_service import get_db_connection
from .email_service import send_notification_email, generate_ics_content


def approve_leave_request(application_id: str) -> bool:
    """Finalize approval for a leave request and notify the employee.

    Parameters
    ----------
    application_id:
        Unique identifier for the leave application.

    Returns
    -------
    bool
        ``True`` if the request was updated and an email was dispatched,
        otherwise ``False``.
    """
    conn = get_db_connection()
    if conn is None:
        return False

    try:
        with conn:
            cur = conn.cursor()
            # Update status to approved
            cur.execute(
                """
                UPDATE leave_applications
                   SET status = 'Approved',
                       updated_at = CURRENT_TIMESTAMP
                 WHERE application_id = ?
                """,
                (application_id,),
            )
            if cur.rowcount == 0:
                return False

            # Fetch data needed for the notification email
            cur.execute(
                """
                SELECT la.start_date, la.end_date, la.leave_type, e.personal_email
                  FROM leave_applications AS la
                  JOIN employees AS e ON la.employee_id = e.id
                 WHERE la.application_id = ?
                """,
                (application_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return False

    start_date, end_date, leave_type, employee_email = row

    subject = f"Leave Approved: {leave_type}"
    body = (
        f"Your {leave_type} leave from {start_date} to {end_date} has been approved."
    )

    ics: Optional[str]
    try:
        ics = generate_ics_content(start_date, end_date, subject, body)
    except Exception:
        ics = None

    send_notification_email(employee_email, subject, body, ics_content=ics)
    return True

