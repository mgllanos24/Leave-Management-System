"""
Service: Balance Manager. Purpose: Calculate and update employee leave balances.
TODO: implement functions and add error handling.
"""

from .database_service import get_db_connection, db_lock
from datetime import datetime
import uuid
import time

# Moved from server.py - balance management functions
# @tweakable balance management configuration
AUTO_UPDATE_BALANCES = True
PREVENT_NEGATIVE_BALANCES = True
ENABLE_BALANCE_AUDIT = True
PRIVILEGE_LEAVE_TYPES = {'Annual Leave', 'Vacation / Annual Leave', 'Personal Leave'}
ADMIN_CAN_EDIT_REMAINING_LEAVE = True
DEFAULT_PRIVILEGE_LEAVE = 15
DEFAULT_SICK_LEAVE = 7

def initialize_employee_balances(employee_id, year=None):
    """Initialize leave balances for a new employee"""
    # @tweakable maximum retry attempts for database operations
    MAX_DB_INIT_RETRIES = 3
    # @tweakable delay between database retry attempts in seconds  
    DB_INIT_RETRY_DELAY = 0.5
    # @tweakable whether to enable detailed balance initialization logging
    DETAILED_BALANCE_INIT_LOGGING = True
    
    if year is None:
        year = datetime.now().year
    
    for attempt in range(MAX_DB_INIT_RETRIES):
        conn = None
        with db_lock:
            try:
                if DETAILED_BALANCE_INIT_LOGGING and attempt > 0:
                    print(f"🔄 Balance initialization attempt {attempt + 1}/{MAX_DB_INIT_RETRIES} for employee {employee_id}")

                conn = get_db_connection()
                current_time = datetime.now().isoformat()

                # Get employee details with better error handling
                cursor = conn.execute('SELECT annual_leave, sick_leave, first_name, surname FROM employees WHERE id = ? AND is_active = 1', (employee_id,))
                employee = cursor.fetchone()

                if not employee:
                    raise ValueError(f"Employee {employee_id} not found in database")

                if DETAILED_BALANCE_INIT_LOGGING:
                    print(f"✅ Found employee for balance init: {employee['first_name']} {employee['surname']}")

                privilege_allocation = employee['annual_leave'] or DEFAULT_PRIVILEGE_LEAVE
                sick_allocation = employee['sick_leave'] or DEFAULT_SICK_LEAVE

                # Check if balances already exist
                existing_cursor = conn.execute('''
                    SELECT COUNT(*) as count FROM leave_balances
                    WHERE employee_id = ? AND year = ?
                ''', (employee_id, year))

                existing_count = existing_cursor.fetchone()['count']

                if existing_count > 0:
                    if DETAILED_BALANCE_INIT_LOGGING:
                        print(f"ℹ️ Leave balances already exist for employee {employee_id} (year {year})")
                    conn.close()
                    return True

                # Initialize privilege leave balance
                conn.execute('''
                    INSERT OR REPLACE INTO leave_balances
                    (id, employee_id, balance_type, allocated_days, used_days, remaining_days, year, last_updated, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(uuid.uuid4()),
                    employee_id,
                    'PRIVILEGE',
                    privilege_allocation,
                    0,
                    privilege_allocation,
                    year,
                    current_time,
                    current_time
                ))

                # Initialize sick leave balance
                conn.execute('''
                    INSERT OR REPLACE INTO leave_balances
                    (id, employee_id, balance_type, allocated_days, used_days, remaining_days, year, last_updated, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(uuid.uuid4()),
                    employee_id,
                    'SICK',
                    sick_allocation,
                    0,
                    sick_allocation,
                    year,
                    current_time,
                    current_time
                ))

                conn.commit()

                if DETAILED_BALANCE_INIT_LOGGING:
                    print(f"✅ Successfully initialized leave balances for employee {employee_id}")

                return True

            except Exception as e:
                if conn:
                    conn.rollback()

                if attempt >= MAX_DB_INIT_RETRIES - 1:
                    raise e
                else:
                    if DETAILED_BALANCE_INIT_LOGGING:
                        print(f"⚠️ Balance init attempt {attempt + 1} failed for employee {employee_id}: {e}")
                    time.sleep(DB_INIT_RETRY_DELAY)

            finally:
                if conn:
                    conn.close()
    
    return False

def update_leave_balance(employee_id, balance_type, change_amount, reason, application_id=None, changed_by='SYSTEM'):
    """Update employee leave balance and create audit record"""
    if not AUTO_UPDATE_BALANCES:
        return False
    
    current_time = datetime.now().isoformat()
    current_year = datetime.now().year

    balance_record = None
    with db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.execute('''
                SELECT * FROM leave_balances
                WHERE employee_id = ? AND balance_type = ? AND year = ?
            ''', (employee_id, balance_type, current_year))
            balance_record = cursor.fetchone()
        finally:
            conn.close()

    if not balance_record:
        initialize_employee_balances(employee_id, current_year)
        with db_lock:
            conn = get_db_connection()
            try:
                cursor = conn.execute('''
                    SELECT * FROM leave_balances
                    WHERE employee_id = ? AND balance_type = ? AND year = ?
                ''', (employee_id, balance_type, current_year))
                balance_record = cursor.fetchone()
            finally:
                conn.close()

    if not balance_record:
        raise ValueError(f"Could not initialize balance for employee {employee_id}")

    previous_used = balance_record['used_days']
    previous_remaining = balance_record['remaining_days']

    new_used = previous_used + change_amount
    new_remaining = balance_record['allocated_days'] + balance_record['carryforward_days'] - new_used

    if PREVENT_NEGATIVE_BALANCES and new_remaining < 0:
        raise ValueError(f"Insufficient {balance_type.lower()} leave balance. Required: {change_amount}, Available: {previous_remaining}")

    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute('''
                UPDATE leave_balances
                SET used_days = ?, remaining_days = ?, last_updated = ?
                WHERE employee_id = ? AND balance_type = ? AND year = ?
            ''', (new_used, new_remaining, current_time, employee_id, balance_type, current_year))

            if ENABLE_BALANCE_AUDIT:
                conn.execute('''
                    INSERT INTO leave_balance_history
                    (id, employee_id, balance_type, change_type, change_amount, previous_balance, new_balance, reason, application_id, changed_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(uuid.uuid4()),
                    employee_id,
                    balance_type,
                    'DEDUCTION' if change_amount > 0 else 'ADDITION',
                    abs(change_amount),
                    previous_remaining,
                    new_remaining,
                    reason,
                    application_id,
                    changed_by,
                    current_time
                ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    return True

def process_leave_application_balance(application_id, new_status, changed_by='SYSTEM'):
    """Adjust leave balances when an application's status changes."""
    employee_id = None
    balance_type = None
    total_days = 0
    last_action = None
    balance_exists = None
    current_year = datetime.now().year

    with db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.execute(
                'SELECT employee_id, leave_type, total_days FROM leave_applications WHERE id = ?',
                (application_id,),
            )
            application = cursor.fetchone()
            if not application:
                raise ValueError(f"Leave application {application_id} not found")

            employee_id = application['employee_id']
            leave_type = application['leave_type']
            total_days = float(application['total_days'])

            balance_type = 'PRIVILEGE' if leave_type in PRIVILEGE_LEAVE_TYPES else 'SICK'

            cursor = conn.execute(
                'SELECT id FROM leave_balances WHERE employee_id = ? AND balance_type = ? AND year = ?',
                (employee_id, balance_type, current_year),
            )
            balance_exists = cursor.fetchone()

            cursor = conn.execute(
                'SELECT change_type FROM leave_balance_history WHERE application_id = ? ORDER BY created_at DESC LIMIT 1',
                (application_id,),
            )
            last_action = cursor.fetchone()
        finally:
            conn.close()

    if not balance_exists:
        initialize_employee_balances(employee_id, current_year)

    reason = f"Leave application status changed to {new_status}"

    if new_status == 'Approved':
        if not last_action or last_action['change_type'] != 'DEDUCTION':
            update_leave_balance(
                employee_id,
                balance_type,
                total_days,
                reason,
                application_id=application_id,
                changed_by=changed_by,
            )
    else:
        if last_action and last_action['change_type'] == 'DEDUCTION':
            update_leave_balance(
                employee_id,
                balance_type,
                -total_days,
                reason,
                application_id=application_id,
                changed_by=changed_by,
            )

    return True

def get_employee_balances(employee_id=None):
    """Get employee balances with optional filtering"""
    with db_lock:
        conn = get_db_connection()
        try:
            if employee_id:
                cursor = conn.execute(
                    'SELECT * FROM leave_balances WHERE employee_id = ? ORDER BY balance_type, year',
                    (employee_id,)
                )
            else:
                cursor = conn.execute('SELECT * FROM leave_balances ORDER BY employee_id, balance_type')

            results = [dict(row) for row in cursor.fetchall()]
            return results
        finally:
            conn.close()

# @tweakable: The name of the person or system making manual balance edits.
MANUAL_EDIT_ACTOR_NAME = "Admin"

def update_balances_from_admin_edit(employee_id, new_remaining_pl, new_remaining_sl):
    """
    Updates the remaining leave balances for an employee directly.
    This is typically triggered by an administrator's manual edit.
    """
    # @tweakable: Whether to allow admins to directly edit remaining leave balances.
    if not ADMIN_CAN_EDIT_REMAINING_LEAVE:
        return

    with db_lock:
        conn = get_db_connection()
        try:
            current_time = datetime.now().isoformat()
            current_year = datetime.now().year

            # --- Update Privilege Leave ---
            cursor_pl = conn.execute(
                'SELECT id, remaining_days, used_days, allocated_days FROM leave_balances WHERE employee_id = ? AND balance_type = "PRIVILEGE" AND year = ?',
                (employee_id, current_year)
            )
            current_pl = cursor_pl.fetchone()

            if current_pl and float(current_pl['remaining_days']) != float(new_remaining_pl):
                new_used_pl = current_pl['allocated_days'] - float(new_remaining_pl)

                conn.execute(
                    'UPDATE leave_balances SET remaining_days = ?, used_days = ?, last_updated = ? WHERE id = ?',
                    (new_remaining_pl, new_used_pl, current_time, current_pl['id'])
                )

            # --- Update Sick Leave ---
            cursor_sl = conn.execute(
                'SELECT id, remaining_days, used_days, allocated_days FROM leave_balances WHERE employee_id = ? AND balance_type = "SICK" AND year = ?',
                (employee_id, current_year)
            )
            current_sl = cursor_sl.fetchone()

            if current_sl and float(current_sl['remaining_days']) != float(new_remaining_sl):
                new_used_sl = current_sl['allocated_days'] - float(new_remaining_sl)

                conn.execute(
                    'UPDATE leave_balances SET remaining_days = ?, used_days = ?, last_updated = ? WHERE id = ?',
                    (new_remaining_sl, new_used_sl, current_time, current_sl['id'])
                )

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def _todo():
    """Placeholder to keep the module importable."""
    return None