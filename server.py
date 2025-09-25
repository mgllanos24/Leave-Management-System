import http.server
import socketserver
import json
import urllib.parse
import sys
import os
import uuid
import logging
import sqlite3
from datetime import datetime, timedelta  # @tweakable include timedelta for date calculations
from http.cookies import SimpleCookie

# Import service modules
from services.database_service import init_database, get_db_connection, db_lock
from services.employee_service import create_employee, update_employee, delete_employee, get_employees, get_employee_by_email
# @tweakable import employee validation constants to fix undefined variable errors
from services.employee_service import (
    ENABLE_EMPLOYEE_VALIDATION, VALIDATE_EMAIL_UNIQUENESS, MAX_FIRSTNAME_LENGTH,
    MAX_SURNAME_LENGTH, DEFAULT_PRIVILEGE_LEAVE, ENABLE_EMPLOYEE_AUDIT
)
from services.balance_manager import (
    initialize_employee_balances,
    update_leave_balance,
    get_employee_balances,
    update_balances_from_admin_edit,
    process_leave_application_balance,
    reset_all_balances,
)
from services.email_service import (
    send_notification_email,
    generate_ics_content,
    SMTP_SERVER,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
)

# Configure logging to write to ``server.log`` if possible.  If creating the
# log file fails (e.g. due to permissions issues), fall back to logging to
# ``stderr`` so the server can still run.
try:
    file_handler = logging.FileHandler("server.log")
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, logging.StreamHandler()])
except Exception as log_err:  # noqa: BLE001 - broad exception to keep server running
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    logging.warning(
        "Falling back to stderr logging because server.log could not be opened: %s",
        log_err,
    )

# Load environment variables from a .env file if present
def _load_env(path: str = ".env") -> None:
    """Populate ``os.environ`` from a ``.env`` file if it exists."""
    if os.path.exists(path):
        with open(path) as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

_load_env()

# Configure logging
LOG_FILE = os.getenv("LOG_FILE", "server.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)

# Default sick leave allocation
DEFAULT_SICK_LEAVE = 5

# Standard number of working hours in a full day. Used to translate between
# hourly requests and legacy day-based balance tracking.
WORK_HOURS_PER_DAY = float(os.getenv("WORK_HOURS_PER_DAY", 8))

# @tweakable server configuration
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "mgllanos@gmail.com")
if not ADMIN_EMAIL:
    raise RuntimeError("ADMIN_EMAIL environment variable is required")
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# @tweakable employee management configuration - define missing constants
AUTO_CREATE_BALANCE_RECORDS = True

# Track active admin session tokens
active_admin_tokens = set()

def _calculate_total_days_legacy(
    start_date,
    end_date,
    start_day_type='full',
    end_day_type='full',
    holidays=None,
):
    """Legacy day-based calculation preserved for backward compatibility."""

    if not start_date or not end_date:
        return 0

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return 0

    if end < start:
        return 0

    holidays = holidays or set()

    total = 0
    current = start
    while current <= end:
        if current.weekday() < 5 and current.isoformat() not in holidays:
            total += 1
            if current == start and start_day_type != 'full':
                total -= 0.5
            if current == end and end_day_type != 'full':
                total -= 0.5
        current += timedelta(days=1)

    return total


def calculate_total_hours(
    start_date,
    end_date,
    start_time=None,
    end_time=None,
    holidays=None,
    start_day_type='full',
    end_day_type='full',
):
    """Compute total leave hours excluding weekends and configured holidays."""

    if not start_date or not end_date:
        return 0.0

    holidays = holidays or set()

    if start_time or end_time:
        start_time_str = start_time or (
            '13:00' if start_day_type == 'pm' else '00:00'
        )
        end_time_str = end_time or (
            '12:00' if end_day_type == 'am' else '23:59'
        )

        try:
            start_dt = datetime.strptime(
                f"{start_date} {start_time_str}", "%Y-%m-%d %H:%M"
            )
            end_dt = datetime.strptime(
                f"{end_date} {end_time_str}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            return 0.0

        if end_dt <= start_dt:
            return 0.0

        total_hours = 0.0
        current_date = start_dt.date()
        final_date = end_dt.date()

        while current_date <= final_date:
            day_start = datetime.combine(current_date, datetime.min.time())
            day_end = day_start + timedelta(days=1)
            window_start = max(start_dt, day_start)
            window_end = min(end_dt, day_end)

            if window_end > window_start:
                iso_date = current_date.isoformat()
                if current_date.weekday() < 5 and iso_date not in holidays:
                    delta = window_end - window_start
                    total_hours += delta.total_seconds() / 3600.0

            current_date += timedelta(days=1)

        return round(total_hours, 2)

    legacy_days = _calculate_total_days_legacy(
        start_date,
        end_date,
        start_day_type,
        end_day_type,
        holidays,
    )
    return round(legacy_days * WORK_HOURS_PER_DAY, 2)


def calculate_total_days(
    start_date,
    end_date,
    start_day_type='full',
    end_day_type='full',
    holidays=None,
    start_time=None,
    end_time=None,
):
    """Return total leave in working days derived from hourly calculation."""

    total_hours = calculate_total_hours(
        start_date,
        end_date,
        start_time=start_time,
        end_time=end_time,
        holidays=holidays,
        start_day_type=start_day_type,
        end_day_type=end_day_type,
    )

    if total_hours == 0:
        return 0

    return round(total_hours / WORK_HOURS_PER_DAY, 4)

def next_workday(date_str: str, holidays: set[str] | None = None) -> str | None:
    """Return the next working day after ``date_str``.

    Weekends (Saturday and Sunday) and any dates in ``holidays`` are skipped.
    If ``date_str`` is empty or cannot be parsed, ``None`` is returned.
    """
    if not date_str:
        return None
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

    holidays = holidays or set()

    while True:
        date += timedelta(days=1)
        if date.weekday() < 5 and date.isoformat() not in holidays:
            return date.isoformat()


def next_workday(date_str, holidays=None):
    """Return the next working day after ``date_str``.

    Skips weekends and any dates provided in the ``holidays`` set.
    """

    if not date_str:
        return None

    try:
        current = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

    holidays = holidays or set()

    while True:
        current += timedelta(days=1)
        if current.weekday() < 5 and current.isoformat() not in holidays:
            return current.isoformat()


def format_leave_request_email(
    employee_name,
    application_id,
    leave_type,
    start_date,
    start_time,
    end_date,
    end_time,
    return_date,
    total_hours,
    total_days,
    reason,
    date_applied,
):
    """Build a multi-line email body for a leave request notification."""

    def _format_datetime(date_str: str, time_str: str | None) -> str:
        if not date_str:
            return ""
        if time_str:
            try:
                dt = datetime.fromisoformat(f"{date_str}T{time_str}")
                return dt.strftime("%B %d, %Y %I:%M %p")
            except Exception:  # noqa: BLE001 - fall back to raw values
                return f"{date_str} {time_str}"
        try:
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%B %d, %Y")
        except Exception:  # noqa: BLE001 - fall back to raw value
            return date_str

    try:
        applied_dt = datetime.fromisoformat(date_applied)
        formatted_applied = applied_dt.strftime("%B %d, %Y %I:%M %p")
    except Exception:  # noqa: BLE001 - if parsing fails, use raw value
        formatted_applied = date_applied

    start_display = _format_datetime(start_date, start_time)
    end_display = _format_datetime(end_date, end_time)

    total_hours_display = f"{float(total_hours):.2f}" if total_hours else "0.00"
    total_days_display = f"{float(total_days):.2f}" if total_days else "0.00"

    return f"""A new leave request has been submitted and requires your approval.

 Employee Details
 - Employee Name: {employee_name}
 - Application ID: {application_id}

 Leave Request Details
 - Leave Type: {leave_type}
 - Start: {start_display}
 - End: {end_display}
 - Return Date: {return_date}
 - Total Hours: {total_hours_display}
 - Equivalent Days: {total_days_display}

Reason for Leave
{reason or 'No additional details provided.'}

Submitted On: {formatted_applied}

Please log in to the Leave Management System to review and take action.
Status: Pending Approval

Best regards,
Leave Management System"""

class LeaveManagementHandler(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        """Ensure JavaScript files are served with UTF-8 charset"""
        base, ext = os.path.splitext(path)
        if ext == '.js':
            return 'application/javascript; charset=UTF-8'
        return super().guess_type(path)

    def send_cors_headers(self):
        """Add CORS headers to the response"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()
    def do_POST(self):
        if self.path == '/api/bootstrap_employee':
            self.handle_bootstrap_employee()
        elif self.path.startswith('/api/'):
            self.handle_api_request()
        else:
            self.send_error(404, "Not Found")
    
    def do_GET(self):
        if self.path.startswith('/api/'):
            self.handle_api_request()
        elif self.path == '/api/config/admin_email':
            self.send_json_response({'admin_email': ADMIN_EMAIL})
        else:
            # Serve static files
            super().do_GET()
    
    def do_PUT(self):
        if self.path.startswith('/api/'):
            self.handle_api_request()
        else:
            self.send_error(404, "Not Found")
    
    def do_DELETE(self):
        if self.path.startswith('/api/'):
            self.handle_api_request()
        else:
            self.send_error(404, "Not Found")
    
    def handle_api_request(self):
        """Handle API requests for database operations"""
        try:
            parsed = urllib.parse.urlparse(self.path)
            path_parts = parsed.path.split('/')
            if len(path_parts) < 3:
                self.send_error(400, "Invalid API path")
                return

            collection = path_parts[2]

            if self.command == 'GET':
                self.handle_get_request(collection, path_parts, parsed.query)
            elif self.command == 'POST':
                if collection == 'holiday' and len(path_parts) > 3 and path_parts[3] == 'auto_populate':
                    self.handle_auto_populate_holidays()
                else:
                    self.handle_post_request(collection)
            elif self.command == 'PUT':
                self.handle_put_request(collection, path_parts)
            elif self.command == 'DELETE':
                self.handle_delete_request(collection, path_parts)
            else:
                self.send_error(405, "Method Not Allowed")
                
        except Exception as e:
            logging.error("API request error: %s", e)
            self.send_error(500, f"Internal Server Error: {str(e)}")
    
    def handle_get_request(self, collection, path_parts, query_string):
        """Handle GET requests"""
        if collection == 'next_application_id':
            # Generate unique application ID similar to creation logic
            next_id = f"APP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
            self.send_json_response({'application_id': next_id})
            return

        with db_lock:
            conn = get_db_connection()
            try:
                query = urllib.parse.parse_qs(query_string)
                
                # @tweakable handle config endpoint for admin email retrieval
                if collection == 'config' and len(path_parts) > 3:
                    config_key = path_parts[3]
                    if config_key == 'admin_email':
                        results = {'admin_email': ADMIN_EMAIL}
                        self.send_json_response(results)
                        return
                    else:
                        self.send_error(404, f"Config key '{config_key}' not found")
                        return
                elif collection == 'config':
                    # Return all config values
                    results = {
                        'admin_email': ADMIN_EMAIL,
                        'smtp_username': SMTP_USERNAME,
                        'smtp_server': SMTP_SERVER,
                        'smtp_port': SMTP_PORT,
                    }
                    self.send_json_response(results)
                    return
                
                if collection == 'employee':
                    cursor = conn.execute('SELECT * FROM employees WHERE is_active = 1 ORDER BY created_at DESC')
                    results = [dict(row) for row in cursor.fetchall()]
                    
                elif collection == 'leave_application':
                    # Get leave applications with optional employee and status filters
                    base_query = 'SELECT * FROM leave_applications'
                    conditions = []
                    params = []
                    if 'employee_id' in query:
                        conditions.append('employee_id = ?')
                        params.append(query['employee_id'][0])
                    if 'status' in query:
                        conditions.append('status = ?')
                        params.append(query['status'][0])
                    if conditions:
                        base_query += ' WHERE ' + ' AND '.join(conditions)
                    base_query += ' ORDER BY created_at DESC'
                    cursor = conn.execute(base_query, tuple(params))
                    results = [dict(row) for row in cursor.fetchall()]
                elif collection == 'holiday':
                    cursor = conn.execute('SELECT * FROM holidays ORDER BY date')
                    results = [dict(row) for row in cursor.fetchall()]
                elif collection == 'notification':
                    cursor = conn.execute('SELECT * FROM notifications ORDER BY created_at DESC')
                    results = [dict(row) for row in cursor.fetchall()]
                elif collection == 'leave_balance':
                    # Get leave balances with optional employee filter
                    if 'employee_id' in query:
                        cursor = conn.execute(
                            'SELECT * FROM leave_balances WHERE employee_id = ? ORDER BY balance_type, year',
                            (query['employee_id'][0],)
                        )
                    else:
                        cursor = conn.execute('SELECT * FROM leave_balances ORDER BY employee_id, balance_type')
                    results = [dict(row) for row in cursor.fetchall()]
                elif collection == 'leave_balance_history':
                    # Get balance history with optional filters
                    query = 'SELECT * FROM leave_balance_history ORDER BY created_at DESC'
                    cursor = conn.execute(query)
                    results = [dict(row) for row in cursor.fetchall()]
                else:
                    self.send_error(404, f"Collection '{collection}' not found")
                    return
                
                self.send_json_response(results)
                
            finally:
                conn.close()
    
    def handle_post_request(self, collection):
        """Handle POST requests (create new records)"""
        if collection == 'login_admin':
            self.handle_login_admin()
            return
        if collection == 'logout_admin':
            self.handle_logout_admin()
            return
        if collection == 'reset_balances':
            cookie_header = self.headers.get('Cookie', '')
            token = None
            if cookie_header:
                cookie = SimpleCookie()
                cookie.load(cookie_header)
                if 'admin_token' in cookie:
                    token = cookie['admin_token'].value
            if not token or token not in active_admin_tokens:
                self.send_error(403, "Admin authentication required")
                return
            reset_all_balances()
            self.send_json_response({'status': 'balances reset'})
            return
        if collection == 'holiday':
            cookie_header = self.headers.get('Cookie', '')
            token = None
            if cookie_header:
                cookie = SimpleCookie()
                cookie.load(cookie_header)
                if 'admin_token' in cookie:
                    token = cookie['admin_token'].value
            if not token or token not in active_admin_tokens:
                self.send_error(403, "Admin authentication required")
                return
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b''
            data = json.loads(post_data.decode('utf-8')) if post_data else {}

            notification_emails = []
            response_payload = None
            record_id = None

            if collection == 'employee':
                employee_record = create_employee(data)
                record_id = employee_record['id']
                response_payload = employee_record
            else:
                with db_lock:
                    conn = get_db_connection()
                    try:
                        record_id = str(uuid.uuid4())
                        current_time = datetime.now().isoformat()

                        if collection == 'leave_application':
                            app_id = data.get(
                                'application_id',
                                f"APP-{datetime.now().strftime('%Y%m%d')}-{record_id[:8].upper()}"
                            )

                            # Recalculate total days server-side ignoring client-provided value
                            cursor = conn.execute('SELECT date FROM holidays')
                            holidays = {row['date'] for row in cursor.fetchall()}
                            start_time = data.get('start_time')
                            end_time = data.get('end_time')

                            total_hours = calculate_total_hours(
                                data.get('start_date', ''),
                                data.get('end_date', ''),
                                start_time,
                                end_time,
                                holidays,
                                data.get('start_day_type', 'full'),
                                data.get('end_day_type', 'full'),
                            )
                            total_days = calculate_total_days(
                                data.get('start_date', ''),
                                data.get('end_date', ''),
                                data.get('start_day_type', 'full'),
                                data.get('end_day_type', 'full'),
                                holidays,
                                start_time=start_time,
                                end_time=end_time,
                            )

                            if total_hours and total_hours < WORK_HOURS_PER_DAY:
                                return_date = data.get('end_date', '')
                            else:
                                return_date = next_workday(data.get('end_date', ''), holidays) or ""

                            conn.execute(
                                '''
                                INSERT INTO leave_applications (
                                    id, application_id, employee_id, employee_name, start_date, end_date,
                                    start_time, end_time, start_day_type, end_day_type, leave_type,
                                    selected_reasons, reason, total_hours, total_days, status, date_applied,
                                    created_at, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''',
                                (
                                    record_id,
                                    app_id,
                                    data.get('employee_id', ''),
                                    data.get('employee_name', ''),
                                    data.get('start_date', ''),
                                    data.get('end_date', ''),
                                    start_time,
                                    end_time,
                                    data.get('start_day_type', 'full'),
                                    data.get('end_day_type', 'full'),
                                    data.get('leave_type', ''),
                                    json.dumps(data.get('selected_reasons', [])),
                                    data.get('reason', ''),
                                    total_hours,
                                    total_days,
                                    data.get('status', 'Pending'),
                                    current_time,
                                    current_time,
                                    current_time,
                                ),
                            )

                            # Update data with server-calculated fields
                            data['total_hours'] = total_hours
                            data['total_days'] = total_days
                            data['return_date'] = return_date
                            data['application_id'] = app_id
                            data['date_applied'] = current_time

                        elif collection == 'holiday':
                            conn.execute('''
                                INSERT INTO holidays (id, date, name, created_at)
                                VALUES (?, ?, ?, ?)
                            ''', (
                                record_id,
                                data.get('date', ''),
                                data.get('name', ''),
                                current_time
                            ))
                        elif collection == 'notification':
                            conn.execute('''
                                INSERT INTO notifications (id, employee_id, message, read, created_at)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (
                                record_id,
                                data.get('employee_id', ''),
                                data.get('message', ''),
                                data.get('read', 0),
                                current_time
                            ))

                        else:
                            self.send_error(404, f"Collection '{collection}' not found")
                            return

                        conn.commit()

                    finally:
                        conn.close()

            # Initialize leave balances for new employee after releasing the lock
            if collection == 'employee' and AUTO_CREATE_BALANCE_RECORDS:
                try:
                    initialize_employee_balances(record_id)
                except Exception as balance_error:
                    pass

            # Send notification email for newly submitted leave applications
            if collection == 'leave_application':
                admin_email = ADMIN_EMAIL
                subject = "New Leave Request Submitted"
                body = format_leave_request_email(
                    data.get('employee_name', ''),
                    data.get('application_id', ''),
                    data.get('leave_type', ''),
                    data.get('start_date', ''),
                    data.get('start_time'),
                    data.get('end_date', ''),
                    data.get('end_time'),
                    data.get('return_date', ''),
                    data.get('total_hours', 0),
                    data.get('total_days', 0),
                    data.get('reason', ''),
                    data.get('date_applied', ''),
                )
                try:
                    sent, err = send_notification_email(
                        admin_email,
                        subject,
                        body,
                        SMTP_SERVER,
                        SMTP_PORT,
                        SMTP_USERNAME,
                        SMTP_PASSWORD,
                    )
                except Exception as email_error:  # noqa: BLE001 - unexpected failure
                    sent, err = False, str(email_error)

                if sent:
                    logging.info("Notification email sent to %s", admin_email)
                else:
                    logging.error(
                        "Failed to send notification email to %s for application %s: %s",
                        admin_email,
                        record_id,
                        err,
                    )

            email_status = {}
            for recipient, to_addr, subject, body, ics in notification_emails:
                try:
                    sent, err = send_notification_email(
                        to_addr,
                        subject,
                        body,
                        SMTP_SERVER,
                        SMTP_PORT,
                        SMTP_USERNAME,
                        SMTP_PASSWORD,
                        ics_content=ics,
                    )
                    email_status[recipient] = bool(sent)
                    if not sent:
                        logging.warning(
                            "Failed to send email to %s for application %s: %s",
                            to_addr,
                            record_id,
                            err,
                        )
                except Exception as email_err:  # noqa: BLE001 - unexpected failure
                    email_status[recipient] = False
                    logging.exception(
                        "Failed to send email '%s' to %s for application %s",
                        subject,
                        to_addr,
                        record_id,
                    )

            if response_payload is not None:
                response_payload['email_status'] = email_status
            else:
                response_payload = {'email_status': email_status}

            self.send_json_response(response_payload)

        except Exception as e:
            self.send_error(500, f"Error creating record: {str(e)}")
    
    def handle_put_request(self, collection, path_parts):
        """Handle PUT requests (update records)"""
        if len(path_parts) < 4:
            self.send_error(400, "Record ID required for update")
            return

        record_id = path_parts[3]

        if collection == 'holiday':
            cookie_header = self.headers.get('Cookie', '')
            token = None
            if cookie_header:
                cookie = SimpleCookie()
                cookie.load(cookie_header)
                if 'admin_token' in cookie:
                    token = cookie['admin_token'].value
            if not token or token not in active_admin_tokens:
                self.send_error(403, "Admin authentication required")
                return

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b''
            data = json.loads(post_data.decode('utf-8')) if post_data else {}

            notification_emails = []

            if collection == 'employee':
                update_employee(record_id, data)
                if 'remaining_privilege_leave' in data or 'remaining_sick_leave' in data:
                    remaining_pl = data.get('remaining_privilege_leave')
                    remaining_sl = data.get('remaining_sick_leave')
                    if remaining_pl is not None and remaining_sl is not None:
                        update_balances_from_admin_edit(record_id, remaining_pl, remaining_sl)
                response_payload = dict(data)
                response_payload['id'] = record_id
                response_payload['updated_at'] = datetime.now().isoformat()
                self.send_json_response(response_payload)
                return

            with db_lock:
                conn = get_db_connection()
                try:
                    current_time = datetime.now().isoformat()

                    if collection == 'leave_application':
                        # Get current status before update
                        cursor = conn.execute('SELECT status FROM leave_applications WHERE id = ?', (record_id,))
                        current_record = cursor.fetchone()
                        current_status = current_record['status'] if current_record else None
                        
                        new_status = data.get('status', 'Pending')
                        
                        cursor = conn.execute('''
                            UPDATE leave_applications
                            SET status=?, updated_at=?
                            WHERE id=?
                        ''', (
                            new_status,
                            current_time,
                            record_id
                        ))

                        if cursor.rowcount == 0:
                            self.send_error(404, "Record not found")
                            return

                        # Commit status update before processing balances
                        conn.commit()

                        # Process balance changes if status changed
                        if current_status and current_status != new_status:
                            try:
                                process_leave_application_balance(record_id, new_status, 'ADMIN')
                            except Exception as balance_error:
                                logging.warning(
                                    "Balance processing error for %s: %s",
                                    record_id,
                                    balance_error,
                                )
                                # Don't fail the entire request if balance update fails

                        conn.commit()

                        # Fetch leave and employee details for notification emails
                        try:

                            cursor = conn.execute(
                                'SELECT employee_id, employee_name, start_date, end_date, start_time, end_time, total_hours, total_days, application_id, leave_type FROM leave_applications WHERE id = ?',
                                (record_id,),
                            )
                            app_info = cursor.fetchone()
                            if app_info:
                                employee_id = app_info['employee_id']
                                leave_type = app_info['leave_type']
                                app_id = app_info['application_id']
                                cursor = conn.execute(
                                    'SELECT personal_email FROM employees WHERE id = ?',
                                    (employee_id,),
                                )
                                emp = cursor.fetchone()
                                employee_email = emp['personal_email'] if emp else None

                                start_date = app_info['start_date']
                                end_date = app_info['end_date']
                                start_time = app_info['start_time']
                                end_time = app_info['end_time']
                                raw_hours = app_info['total_hours']
                                raw_days = app_info['total_days']
                                total_hours = float(raw_hours) if raw_hours is not None else 0.0
                                total_days = float(raw_days) if raw_days is not None else 0.0
                                employee_name = app_info['employee_name']
                                cursor = conn.execute('SELECT date FROM holidays')
                                holidays = {row['date'] for row in cursor.fetchall()}
                                status_word = 'approved' if new_status == 'Approved' else 'rejected'
                                return_date = next_workday(end_date, holidays)

                                admin_subject = f"Leave application {status_word}: {employee_name}"

                                admin_body = (
                                    f"Leave request for {employee_name} (Application ID: {app_id}) has been {status_word}.\n\n"
                                    "Request Details:\n"
                                    f"- Leave Type: {leave_type}\n"
                                    f"- Start: {start_date} {start_time or ''}\n"
                                    f"- End: {end_date} {end_time or ''}\n"
                                    f"- Return Date: {return_date}\n"
                                    f"- Total Hours: {total_hours}\n"
                                    f"- Equivalent Days: {total_days}\n"
                                )
                                employee_subject = f"Your leave application has been {status_word}"

                                employee_body = f"""Dear {employee_name},

Your leave request (Application ID: {app_id}) has been {status_word}.

Request Details:
- Leave Type: {leave_type}
- Start: {start_date} {start_time or ''}
- End: {end_date} {end_time or ''}
- Total Hours: {total_hours}
- Equivalent Days: {total_days}

Please plan accordingly.

Best regards,
HR Department
"""

                                ics_content = None
                                if new_status == 'Approved':
                                    ics_content = generate_ics_content(
                                        start_date,
                                        end_date,
                                        summary=f"Leave for {employee_name}",
                                        description=(
                                            f"Approved leave from {start_date} {start_time or ''} to {end_date} {end_time or ''} "
                                            f"({total_hours} hours / {total_days} days)"
                                        ),
                                        start_time=start_time,
                                        end_time=end_time,
                                    )

                                admin_email = ADMIN_EMAIL
                                if admin_email:
                                    notification_emails.append(
                                        (
                                            'admin',
                                            admin_email,
                                            admin_subject,
                                            admin_body,
                                            ics_content,
                                        )
                                    )
                                else:
                                    logging.warning(
                                        "Admin email missing for application %s; skipping admin notification",
                                        record_id,
                                    )

                                if employee_email:
                                    notification_emails.append(
                                        (
                                            'employee',
                                            employee_email,
                                            employee_subject,
                                            employee_body,
                                            None,
                                        )
                                    )
                                else:
                                    logging.warning(
                                        "Employee email missing for employee %s; skipping employee notification",
                                        employee_id,
                                    )
                        except Exception as prep_err:
                            logging.warning(
                                "Email notification preparation failed for %s: %s",
                                record_id,
                                prep_err,
                            )

                        response_payload = dict(data)
                        response_payload['id'] = record_id
                        response_payload['updated_at'] = current_time

                    elif collection == 'leave_balance':
                        remaining_days = data.get('remaining_days')
                        if remaining_days is None:
                            self.send_error(400, "remaining_days is required")
                            return

                        cursor = conn.execute(
                            'SELECT allocated_days FROM leave_balances WHERE id = ?',
                            (record_id,),
                        )
                        record = cursor.fetchone()
                        if not record:
                            self.send_error(404, "Record not found")
                            return

                        allocated_days = record['allocated_days']
                        used_days = allocated_days - float(remaining_days)

                        cursor = conn.execute(
                            'UPDATE leave_balances SET remaining_days = ?, used_days = ?, last_updated = ? WHERE id = ?',
                            (remaining_days, used_days, current_time, record_id),
                        )

                        if cursor.rowcount == 0:
                            self.send_error(404, "Record not found")
                            return

                        conn.commit()

                        cursor = conn.execute(
                            'SELECT * FROM leave_balances WHERE id = ?', (record_id,)
                        )
                        updated = cursor.fetchone()
                        response_payload = dict(updated) if updated else {
                            'id': record_id,
                            'remaining_days': remaining_days,
                            'used_days': used_days,
                            'last_updated': current_time,
                        }

                    else:
                        self.send_error(404, f"Collection '{collection}' not found")
                        return

                finally:
                    conn.close()

            email_status = {}
            for recipient, to_addr, subject, body, ics in notification_emails:
                try:
                    sent, err = send_notification_email(
                        to_addr,
                        subject,
                        body,
                        SMTP_SERVER,
                        SMTP_PORT,
                        SMTP_USERNAME,
                        SMTP_PASSWORD,
                        ics_content=ics,
                    )
                    email_status[recipient] = bool(sent)
                    if not sent:
                        logging.warning(
                            "Failed to send email to %s for application %s: %s",
                            to_addr,
                            record_id,
                            err,
                        )
                except Exception as email_err:  # noqa: BLE001 - unexpected failure
                    email_status[recipient] = False
                    logging.exception(
                        "Failed to send email '%s' to %s for application %s",
                        subject,
                        to_addr,
                        record_id,
                    )

            if response_payload is not None:
                response_payload['email_status'] = email_status
            else:
                response_payload = {'email_status': email_status}

            self.send_json_response(response_payload)

        except ValueError as e:
            self.send_error(400, str(e))
        except sqlite3.Error as e:
            self.send_error(500, f"Database error: {e}")
        except Exception as e:
            self.send_error(500, f"Error updating record: {str(e)}")
    
    def handle_delete_request(self, collection, path_parts):
        """Handle DELETE requests"""
        if len(path_parts) < 4:
            self.send_error(400, "Record ID required for delete")
            return

        record_id = path_parts[3]

        if collection == 'holiday':
            cookie_header = self.headers.get('Cookie', '')
            token = None
            if cookie_header:
                cookie = SimpleCookie()
                cookie.load(cookie_header)
                if 'admin_token' in cookie:
                    token = cookie['admin_token'].value
            if not token or token not in active_admin_tokens:
                self.send_error(403, "Admin authentication required")
                return

        with db_lock:
            conn = get_db_connection()
            try:
                if collection == 'employee':
                    # Soft delete for employees (maintain data integrity)
                    cursor = conn.execute('UPDATE employees SET is_active = 0, updated_at = ? WHERE id = ? AND is_active = 1',
                                        (datetime.now().isoformat(), record_id))

                    if ENABLE_EMPLOYEE_AUDIT:
                        logging.info("Employee soft deleted: %s", record_id)
                
                elif collection == 'leave_application':
                    cursor = conn.execute('DELETE FROM leave_applications WHERE id=?', (record_id,))
                elif collection == 'holiday':
                    cursor = conn.execute('DELETE FROM holidays WHERE id=?', (record_id,))
                elif collection == 'notification':
                    cursor = conn.execute('DELETE FROM notifications WHERE id=?', (record_id,))
                else:
                    self.send_error(404, f"Collection '{collection}' not found")
                    return
                
                if conn.total_changes == 0:
                    self.send_error(404, "Record not found")
                    return
                
                conn.commit()
                
                self.send_json_response({"success": True, "deleted_id": record_id})

            finally:
                conn.close()

    def handle_auto_populate_holidays(self):
        """Handle automatic holiday population"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else b''
            data = json.loads(body.decode('utf-8')) if body else {}
            holidays = data.get('holidays', [])

            with db_lock:
                conn = get_db_connection()
                try:
                    conn.execute('DELETE FROM holidays')
                    now = datetime.now().isoformat()
                    for h in holidays:
                        conn.execute(
                            'INSERT INTO holidays (id, date, name, created_at) VALUES (?, ?, ?, ?)',
                            (str(uuid.uuid4()), h.get('date', ''), h.get('name', ''), now)
                        )
                    conn.commit()
                finally:
                    conn.close()

            self.send_json_response({'status': 'ok', 'inserted': len(holidays)})
        except Exception as e:
            self.send_error(500, f'Failed to auto populate holidays: {e}')

    def _safe_write(self, data: bytes):
        """Safely finalize the response by sending headers and body."""
        try:
            self.end_headers()
        except (ConnectionError, BrokenPipeError) as e:
            logging.warning("Connection lost while sending headers: %s", e)
            return
        try:
            self.wfile.write(data)
        except (ConnectionError, BrokenPipeError) as e:
            logging.warning("Connection lost while writing body: %s", e)

    def send_json_response(self, data, status=200):
        """Send JSON response with CORS headers"""
        response_data = json.dumps(data, ensure_ascii=False, indent=2)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_cors_headers()
        self.send_header('Content-Length', str(len(response_data.encode('utf-8'))))
        self._safe_write(response_data.encode('utf-8'))

    def send_error(self, code, message=None, explain=None):
        """Send error response with CORS headers"""
        self.send_response(code, message)
        self.send_header('Content-Type', 'application/json')
        self.send_cors_headers()
        error_message = message if message else self.responses.get(code, ('', ''))[0]
        self._safe_write(json.dumps({'error': error_message}).encode('utf-8'))

    def handle_login_admin(self):
        """Validate admin credentials and set auth cookie"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length else b'{}'
            data = json.loads(body.decode('utf-8'))
            username = data.get('username', '')
            password = data.get('password', '')

            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                token = uuid.uuid4().hex
                active_admin_tokens.add(token)
                self.send_response(200)
                self.send_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.send_header('Set-Cookie', f'admin_token={token}; Path=/')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True}).encode('utf-8'))
            else:
                self.send_error(401, 'Invalid credentials')
        except Exception as e:
            self.send_error(500, f'Login failed: {str(e)}')

    def handle_logout_admin(self):
        """Handle admin logout by clearing token and cookie"""
        cookie_header = self.headers.get('Cookie', '')
        token = None
        if cookie_header:
            cookie = SimpleCookie()
            cookie.load(cookie_header)
            if 'admin_token' in cookie:
                token = cookie['admin_token'].value

        if token and token in active_admin_tokens:
            active_admin_tokens.discard(token)

        self.send_response(200)
        self.send_cors_headers()
        self.send_header('Content-Type', 'application/json')
        # Clear the admin token cookie
        self.send_header('Set-Cookie', 'admin_token=; Path=/; Max-Age=0')
        self.end_headers()
        self.wfile.write(json.dumps({'success': True}).encode('utf-8'))
    
    def handle_bootstrap_employee(self):
        """Initialize per-employee data/balances on login with enhanced error handling"""
        # @tweakable timeout for bootstrap operations in seconds
        # @tweakable whether to enable detailed bootstrap logging
        DETAILED_BOOTSTRAP_LOGGING = True

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length else b'{}'
            data = json.loads(body.decode('utf-8'))
            email = (data.get('email') or '').strip().lower()

            if not email:
                self.send_error(400, "email is required")
                return

            if DETAILED_BOOTSTRAP_LOGGING:
                logging.info("Bootstrapping employee data for: %s", email)

            # Find employee without holding the DB lock
            conn = get_db_connection()
            try:
                cur = conn.execute('SELECT * FROM employees WHERE personal_email = ? AND is_active = 1', (email,))
                row = cur.fetchone()

                if not row:
                    # Check if employee exists but is inactive
                    inactive_cur = conn.execute('SELECT COUNT(*) as count FROM employees WHERE personal_email = ? AND is_active = 0', (email,))
                    inactive_count = inactive_cur.fetchone()['count']

                    if inactive_count > 0:
                        error_msg = f"Employee with email {email} exists but is inactive"
                    else:
                        error_msg = f"Employee with email {email} not found in database"

                    if DETAILED_BOOTSTRAP_LOGGING:
                        logging.error("Bootstrap failed: %s", error_msg)

                    self.send_error(404, error_msg)
                    return

                employee = dict(row)
            finally:
                conn.close()

            if DETAILED_BOOTSTRAP_LOGGING:
                logging.info(
                    "Found employee: %s %s (ID: %s)",
                    employee['first_name'],
                    employee['surname'],
                    employee['id'],
                )

            # Initialize balances synchronously
            balance_initialized = initialize_employee_balances(employee['id'])
            if not balance_initialized:
                raise Exception("Balance initialization returned false")

            # Query balances for response while holding the DB lock
            with db_lock:
                conn = get_db_connection()
                try:
                    curb = conn.execute('SELECT * FROM leave_balances WHERE employee_id = ? ORDER BY balance_type, year', (employee['id'],))
                    balances = [dict(r) for r in curb.fetchall()]
                finally:
                    conn.close()

            if DETAILED_BOOTSTRAP_LOGGING:
                logging.info(
                    "Bootstrap completed for %s with %d balance records",
                    email,
                    len(balances),
                )

            self.send_json_response({'employee': employee, 'balances': balances})

        except Exception as e:
            logging.error(
                "Bootstrap error for %s: %s",
                email if 'email' in locals() else 'unknown',
                e,
            )
            self.send_error(500, f"Bootstrap failed: {str(e)}")

def run_server(port=8080):
    """Run the HTTP server"""
    try:
        # Initialize database using service
        logging.info("Initializing database...")
        init_database()

        with socketserver.ThreadingTCPServer(("", port), LeaveManagementHandler) as httpd:
            logging.info("Server running at http://localhost:%s", port)
            logging.info("Press Ctrl+C to stop the server")
            httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Server stopped.")
    except OSError as e:
        if e.errno == 48:
            logging.error("Port %s is already in use.", port)
        else:
            logging.error("Error starting server: %s", e)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
