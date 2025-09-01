import http.server
import socketserver
import json
import urllib.parse
import sys
import os
import uuid
import logging
from datetime import datetime  # @tweakable fix datetime import to resolve "module 'datetime' has no attribute 'now'" error

# Import service modules
from services.database_service import init_database, get_db_connection, db_lock
from services.employee_service import create_employee, update_employee, delete_employee, get_employees, get_employee_by_email
# @tweakable import employee validation constants to fix undefined variable errors
from services.employee_service import (
    ENABLE_EMPLOYEE_VALIDATION, VALIDATE_EMAIL_UNIQUENESS, MAX_FIRSTNAME_LENGTH, 
    MAX_SURNAME_LENGTH, DEFAULT_PRIVILEGE_LEAVE, DEFAULT_SICK_LEAVE, ENABLE_EMPLOYEE_AUDIT
)
from services.balance_manager import (
    initialize_employee_balances,
    update_leave_balance,
    get_employee_balances,
    update_balances_from_admin_edit,
    process_leave_application_balance,
)
from services.email_service import (
    send_notification_email,
    SMTP_SERVER,
    SMTP_PORT,
    SMTP_USERNAME,
)

# @tweakable server configuration
ADMIN_EMAIL = "mgllanos@gmail.com"

# @tweakable employee management configuration - define missing constants
AUTO_CREATE_BALANCE_RECORDS = True

class LeaveManagementHandler(http.server.SimpleHTTPRequestHandler):
    def send_cors_headers(self):
        """Add CORS headers to the response"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

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
                self.handle_post_request(collection)
            elif self.command == 'PUT':
                self.handle_put_request(collection, path_parts)
            elif self.command == 'DELETE':
                self.handle_delete_request(collection, path_parts)
            else:
                self.send_error(405, "Method Not Allowed")
                
        except Exception as e:
            print(f"❌ API request error: {e}")
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
                    # Get leave applications with optional employee filter
                    if 'employee_id' in query:
                        cursor = conn.execute(
                            'SELECT * FROM leave_applications WHERE employee_id = ? ORDER BY created_at DESC',
                            (query['employee_id'][0],)
                        )
                    else:
                        cursor = conn.execute('SELECT * FROM leave_applications ORDER BY created_at DESC')
                    results = [dict(row) for row in cursor.fetchall()]
                elif collection == 'holiday':
                    cursor = conn.execute('SELECT * FROM holidays ORDER BY date')
                    results = [dict(row) for row in cursor.fetchall()]
                elif collection == 'approved_leave':
                    cursor = conn.execute('SELECT * FROM approved_leaves ORDER BY start_date')
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
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            with db_lock:
                conn = get_db_connection()
                try:
                    record_id = str(uuid.uuid4())
                    current_time = datetime.now().isoformat()

                    if collection == 'employee':
                        # Enhanced employee validation
                        if ENABLE_EMPLOYEE_VALIDATION:
                            first_name = data.get('first_name', '').strip()
                            surname = data.get('surname', '').strip()
                            email = data.get('personal_email', '').strip().lower()
                            
                            if not first_name or len(first_name) > MAX_FIRSTNAME_LENGTH:
                                raise ValueError(f"Invalid first name (max {MAX_FIRSTNAME_LENGTH} characters)")
                            if not surname or len(surname) > MAX_SURNAME_LENGTH:
                                raise ValueError(f"Invalid surname (max {MAX_SURNAME_LENGTH} characters)")
                            if not email or '@' not in email:
                                raise ValueError("Invalid email address")
                            
                            # Check email uniqueness
                            if VALIDATE_EMAIL_UNIQUENESS:
                                cursor = conn.execute('SELECT id FROM employees WHERE personal_email = ? AND is_active = 1', (email,))
                                if cursor.fetchone():
                                    raise ValueError(f"Employee with email {email} already exists")
                        
                        conn.execute('''
                            INSERT INTO employees (id, first_name, surname, personal_email, annual_leave, sick_leave, is_active, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                        ''', (
                            record_id,
                            data.get('first_name', '').strip(),
                            data.get('surname', '').strip(),
                            data.get('personal_email', '').strip().lower(),
                            data.get('annual_leave', DEFAULT_PRIVILEGE_LEAVE),
                            data.get('sick_leave', DEFAULT_SICK_LEAVE),
                            current_time,
                            current_time
                        ))

                        if ENABLE_EMPLOYEE_AUDIT:
                            print(f"📝 Employee created: {data.get('first_name')} {data.get('surname')} ({data.get('personal_email')})")
                    
                    elif collection == 'leave_application':
                        app_id = data.get('application_id', f"APP-{datetime.now().strftime('%Y%m%d')}-{record_id[:8].upper()}")
                        conn.execute('''
                            INSERT INTO leave_applications (
                                id, application_id, employee_id, employee_name, start_date, end_date,
                                start_day_type, end_day_type, leave_type, selected_reasons, reason,
                                total_days, status, date_applied, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            record_id,
                            app_id,
                            data.get('employee_id', ''),
                            data.get('employee_name', ''),
                            data.get('start_date', ''),
                            data.get('end_date', ''),
                            data.get('start_day_type', 'full'),
                            data.get('end_day_type', 'full'),
                            data.get('leave_type', ''),
                            json.dumps(data.get('selected_reasons', [])),
                            data.get('reason', ''),
                            data.get('total_days', 0),
                            data.get('status', 'Pending'),
                            current_time,
                            current_time,
                            current_time
                        ))
                    
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
                    elif collection == 'approved_leave':
                        conn.execute('''
                            INSERT INTO approved_leaves (id, employee_id, start_date, end_date, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (
                            record_id,
                            data.get('employee_id', ''),
                            data.get('start_date', ''),
                            data.get('end_date', ''),
                            current_time,
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
                body = (
                    f"Employee: {data.get('employee_name', 'Unknown')}\n"
                    f"Leave type: {data.get('leave_type', '')}\n"
                    f"Dates: {data.get('start_date', '')} to {data.get('end_date', '')}\n"
                    f"Total days: {data.get('total_days', 0)}\n"
                    f"Reason: {data.get('reason', '')}"
                )
                try:
                    if send_notification_email(admin_email, subject, body):
                        logging.info("Notification email sent to %s", admin_email)
                    else:
                        logging.error("Failed to send notification email to %s", admin_email)
                except Exception as email_error:
                    logging.error("Error sending notification email: %s", email_error)

            # Return the created record
            created_record = dict(data)
            created_record['id'] = record_id
            created_record['created_at'] = current_time

            self.send_json_response(created_record)
                    
        except Exception as e:
            self.send_error(500, f"Error creating record: {str(e)}")
    
    def handle_put_request(self, collection, path_parts):
        """Handle PUT requests (update records)"""
        if len(path_parts) < 4:
            self.send_error(400, "Record ID required for update")
            return
        
        record_id = path_parts[3]
        
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            with db_lock:
                conn = get_db_connection()
                try:
                    current_time = datetime.now().isoformat()
                    
                    if collection == 'employee':
                        # Enhanced employee update validation
                        if ENABLE_EMPLOYEE_VALIDATION:
                            first_name = data.get('first_name', '').strip()
                            surname = data.get('surname', '').strip()
                            email = data.get('personal_email', '').strip().lower()
                            
                            if first_name and len(first_name) > MAX_FIRSTNAME_LENGTH:
                                raise ValueError(f"Invalid first name (max {MAX_FIRSTNAME_LENGTH} characters)")
                            if surname and len(surname) > MAX_SURNAME_LENGTH:
                                raise ValueError(f"Invalid surname (max {MAX_SURNAME_LENGTH} characters)")
                            if email and '@' not in email:
                                raise ValueError("Invalid email address")
                            
                            # Check email uniqueness (excluding current record)
                            if VALIDATE_EMAIL_UNIQUENESS and email:
                                cursor = conn.execute('SELECT id FROM employees WHERE personal_email = ? AND id != ? AND is_active = 1', (email, record_id))
                                if cursor.fetchone():
                                    raise ValueError(f"Employee with email {email} already exists")
                        
                        cursor = conn.execute('''
                            UPDATE employees
                            SET first_name=?, surname=?, personal_email=?, annual_leave=?, sick_leave=?, updated_at=?
                            WHERE id=? AND is_active=1
                        ''', (
                            data.get('first_name', '').strip(),
                            data.get('surname', '').strip(),
                            data.get('personal_email', '').strip().lower(),
                            data.get('annual_leave', DEFAULT_PRIVILEGE_LEAVE),
                            data.get('sick_leave', DEFAULT_SICK_LEAVE),
                            current_time,
                            record_id
                        ))

                        if cursor.rowcount == 0:
                            self.send_error(404, "Record not found")
                            return

                        # @tweakable: Update remaining leave balances if provided by admin
                        if 'remaining_privilege_leave' in data or 'remaining_sick_leave' in data:
                            remaining_pl = data.get('remaining_privilege_leave')
                            remaining_sl = data.get('remaining_sick_leave')
                            if remaining_pl is not None and remaining_sl is not None:
                                update_balances_from_admin_edit(record_id, remaining_pl, remaining_sl)
                        
                        if ENABLE_EMPLOYEE_AUDIT:
                            print(f"📝 Employee updated: {record_id}")

                        conn.commit()

                    elif collection == 'leave_application':
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
                                print(f"⚠️ Balance processing error for {record_id}: {balance_error}")
                                # Don't fail the entire request if balance update fails

                        if new_status == 'Approved' and current_status != 'Approved':
                            cursor = conn.execute('SELECT employee_id, start_date, end_date FROM leave_applications WHERE id = ?', (record_id,))
                            app_info = cursor.fetchone()
                            if app_info:
                                event_id = str(uuid.uuid4())
                                conn.execute('''
                                    INSERT INTO approved_leaves (id, employee_id, start_date, end_date, created_at, updated_at)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                ''', (
                                    event_id,
                                    app_info['employee_id'],
                                    app_info['start_date'],
                                    app_info['end_date'],
                                    current_time,
                                    current_time
                                ))

                        conn.commit()

                        # Fetch leave and employee details for notification emails
                        try:
                            cursor = conn.execute(
                                'SELECT employee_id, employee_name, start_date, end_date, total_days FROM leave_applications WHERE id = ?',
                                (record_id,)
                            )
                            app_info = cursor.fetchone()
                            if app_info:
                                employee_id = app_info['employee_id']
                                cursor = conn.execute(
                                    'SELECT personal_email FROM employees WHERE id = ?',
                                    (employee_id,)
                                )
                                emp = cursor.fetchone()
                                employee_email = emp['personal_email'] if emp else None

                                start_date = app_info['start_date']
                                end_date = app_info['end_date']
                                total_days = app_info['total_days']
                                employee_name = app_info['employee_name']
                                status_word = 'approved' if new_status == 'Approved' else 'rejected'

                                manager_subject = f"Leave application {status_word}: {employee_name}"
                                manager_body = (
                                    f"Leave application for {employee_name} from {start_date} to {end_date} "
                                    f"({total_days} days) has been {status_word}."
                                )
                                employee_subject = f"Your leave application has been {status_word}"
                                employee_body = (
                                    f"Your leave application from {start_date} to {end_date} "
                                    f"({total_days} days) has been {status_word}."
                                )

                                try:
                                    send_notification_email(
                                        ADMIN_EMAIL,
                                        manager_subject,
                                        manager_body,
                                        SMTP_SERVER,
                                        SMTP_PORT,
                                        SMTP_USERNAME,
                                        SMTP_PASSWORD,
                                    )
                                except Exception as email_err:
                                    print(f"⚠️ Failed to notify manager for {record_id}: {email_err}")

                                if employee_email:
                                    try:
                                        send_notification_email(
                                            employee_email,
                                            employee_subject,
                                            employee_body,
                                            SMTP_SERVER,
                                            SMTP_PORT,
                                            SMTP_USERNAME,
                                            SMTP_PASSWORD,
                                        )
                                    except Exception as email_err:
                                        print(f"⚠️ Failed to notify employee {employee_id}: {email_err}")
                        except Exception as prep_err:
                            print(f"⚠️ Email notification preparation failed for {record_id}: {prep_err}")

                    elif collection == 'approved_leave':
                        cursor = conn.execute('''
                            UPDATE approved_leaves
                            SET start_date=?, end_date=?, updated_at=?
                            WHERE id=?
                        ''', (
                            data.get('start_date', ''),
                            data.get('end_date', ''),
                            current_time,
                            record_id
                        ))

                        if cursor.rowcount == 0:
                            self.send_error(404, "Record not found")
                            return

                        conn.commit()

                    else:
                        self.send_error(404, f"Collection '{collection}' not found")
                        return

                    
                    # Return updated record
                    updated_record = dict(data)
                    updated_record['id'] = record_id
                    updated_record['updated_at'] = current_time
                    
                    self.send_json_response(updated_record)
                    
                finally:
                    conn.close()
                    
        except Exception as e:
            self.send_error(500, f"Error updating record: {str(e)}")
    
    def handle_delete_request(self, collection, path_parts):
        """Handle DELETE requests"""
        if len(path_parts) < 4:
            self.send_error(400, "Record ID required for delete")
            return
        
        record_id = path_parts[3]
        
        with db_lock:
            conn = get_db_connection()
            try:
                if collection == 'employee':
                    # Soft delete for employees (maintain data integrity)
                    cursor = conn.execute('UPDATE employees SET is_active = 0, updated_at = ? WHERE id = ? AND is_active = 1', 
                                        (datetime.now().isoformat(), record_id))
                    
                    if ENABLE_EMPLOYEE_AUDIT:
                        print(f"📝 Employee soft deleted: {record_id}")
                
                elif collection == 'leave_application':
                    cursor = conn.execute('DELETE FROM leave_applications WHERE id=?', (record_id,))
                elif collection == 'holiday':
                    cursor = conn.execute('DELETE FROM holidays WHERE id=?', (record_id,))
                elif collection == 'approved_leave':
                    cursor = conn.execute('DELETE FROM approved_leaves WHERE id=?', (record_id,))
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
                print(f"🔄 Bootstrapping employee data for: {email}")

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
                        print(f"❌ Bootstrap failed: {error_msg}")

                    self.send_error(404, error_msg)
                    return

                employee = dict(row)
            finally:
                conn.close()

            if DETAILED_BOOTSTRAP_LOGGING:
                print(f"✅ Found employee: {employee['first_name']} {employee['surname']} (ID: {employee['id']})")

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
                print(f"✅ Bootstrap completed for {email} with {len(balances)} balance records")

            self.send_json_response({'employee': employee, 'balances': balances})

        except Exception as e:
            print(f"❌ Bootstrap error for {email if 'email' in locals() else 'unknown'}: {e}")
            self.send_error(500, f"Bootstrap failed: {str(e)}")

def run_server(port=8080):
    """Run the HTTP server"""
    try:
        # Initialize database using service
        print("📊 Initializing database...")
        init_database()
        
        with socketserver.ThreadingTCPServer(("", port), LeaveManagementHandler) as httpd:
            print(f"Server running at http://localhost:{port}")
            print("Press Ctrl+C to stop the server")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    except OSError as e:
        if e.errno == 48:
            print(f"Error: Port {port} is already in use.")
        else:
            print(f"Error starting server: {e}")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
