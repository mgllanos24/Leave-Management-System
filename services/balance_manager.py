"""Balance manager for calculating and tracking employee leave balances.

Handles initialization, updates, and auditing of leave balances with
configurable options. Future improvements might add support for carry over
policies or additional balance types.
"""

from .database_service import get_db_connection, db_lock
from datetime import datetime
import uuid
import time
import os
from contextlib import nullcontext

# Moved from server.py - balance management functions
# @tweakable balance management configuration
AUTO_UPDATE_BALANCES = True
PREVENT_NEGATIVE_BALANCES = False
ENABLE_BALANCE_AUDIT = True
# Checkbox values that map to privilege leave
# These correspond to the `value` attributes in index.html
# Store privilege leave types as lowercase values to allow
# case-insensitive matching when processing leave types
PRIVILEGE_LEAVE_TYPES = {t.lower() for t in {'personal', 'vacation-annual', 'cash-out'}}
NON_DEDUCTIBLE_LEAVE_TYPES = {'leave-without-pay'}
ADMIN_CAN_EDIT_REMAINING_LEAVE = True
DEFAULT_PRIVILEGE_LEAVE = 15
DEFAULT_SICK_LEAVE = 5

WORK_HOURS_PER_DAY = float(os.getenv("WORK_HOURS_PER_DAY", 8)) or 8.0

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

def update_leave_balance(
    employee_id,
    balance_type,
    change_amount,
    reason,
    application_id=None,
    changed_by='SYSTEM',
    prevent_negative=None,
    conn=None,
    lock=None,
):
    """Update employee leave balance and create audit record"""
    if not AUTO_UPDATE_BALANCES:
        return False

    current_time = datetime.now().isoformat()
    current_year = datetime.now().year

    created_connection = conn is None
    connection = conn or get_db_connection()

    def _lock_context():
        if lock is not None:
            return lock
        return db_lock if created_connection else nullcontext()

    with _lock_context():
        cursor = connection.execute(
            '''
                SELECT * FROM leave_balances
                WHERE employee_id = ? AND balance_type = ? AND year = ?
            ''',
            (employee_id, balance_type, current_year),
        )
        balance_record = cursor.fetchone()

    if not balance_record:
        initialize_employee_balances(employee_id, current_year)
        with _lock_context():
            cursor = connection.execute(
                '''
                    SELECT * FROM leave_balances
                    WHERE employee_id = ? AND balance_type = ? AND year = ?
                ''',
                (employee_id, balance_type, current_year),
            )
            balance_record = cursor.fetchone()

    if not balance_record:
        raise ValueError(f"Could not initialize balance for employee {employee_id}")

    previous_used = balance_record['used_days']
    previous_remaining = balance_record['remaining_days']

    new_used = previous_used + change_amount
    new_remaining = balance_record['allocated_days'] + balance_record['carryforward_days'] - new_used

    if prevent_negative is None:
        prevent_negative = PREVENT_NEGATIVE_BALANCES

    if prevent_negative and new_remaining < -1e-6:
        requested = abs(float(change_amount))
        available = float(previous_remaining)
        raise ValueError(
            f"Insufficient {balance_type.lower()} leave balance: requested {requested:.2f} days, "
            f"but only {available:.2f} days remain."
        )

    try:
        with _lock_context():
            connection.execute(
                '''
                    UPDATE leave_balances
                    SET used_days = ?, remaining_days = ?, last_updated = ?
                    WHERE employee_id = ? AND balance_type = ? AND year = ?
                ''',
                (new_used, new_remaining, current_time, employee_id, balance_type, current_year),
            )

            if ENABLE_BALANCE_AUDIT:
                connection.execute(
                    '''
                        INSERT INTO leave_balance_history
                        (id, employee_id, balance_type, change_type, change_amount, previous_balance, new_balance, reason, application_id, changed_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
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
                        current_time,
                    ),
                )

            if created_connection:
                connection.commit()
    except Exception as e:
        if created_connection:
            connection.rollback()
        raise e
    finally:
        if created_connection:
            connection.close()

    return True

def process_leave_application_balance(
    application_id,
    new_status,
    changed_by='SYSTEM',
    conn=None,
    lock=None,
):
    """Adjust leave balances when an application's status changes."""
    employee_id = None
    balance_type = None
    total_days = 0
    last_action = None
    balance_exists = None
    current_year = datetime.now().year
    is_non_deductible = False
    is_cash_out = False
    is_leave_without_pay = False
    privilege_remaining = None
    last_deduction_entry = None

    using_external_conn = conn is not None

    def _lock_context():
        if conn is None:
            return lock or db_lock
        return lock or nullcontext()

    def _fetch_privilege_remaining():
        nonlocal privilege_remaining, balance_exists
        local_conn = conn or get_db_connection()
        created_connection = conn is None
        try:
            with _lock_context():
                cursor = local_conn.execute(
                    'SELECT id, remaining_days FROM leave_balances WHERE employee_id = ? AND balance_type = "PRIVILEGE" AND year = ?',
                    (employee_id, current_year),
                )
                row = cursor.fetchone()
            if row:
                privilege_remaining = float(row['remaining_days'])
                balance_exists = row
            else:
                privilege_remaining = 0.0
                balance_exists = None
        finally:
            if created_connection:
                local_conn.close()

    def _record_unpaid_history(unpaid_days, reference_balance=None):
        if not ENABLE_BALANCE_AUDIT:
            return

        local_conn = conn or get_db_connection()
        created_connection = conn is None
        try:
            with _lock_context():
                local_conn.execute(
                    'DELETE FROM leave_balance_history WHERE application_id = ? AND change_type = ?',
                    (application_id, 'UNPAID'),
                )

                if unpaid_days > 1e-6:
                    remaining_snapshot = reference_balance if reference_balance is not None else 0.0
                    current_time = datetime.now().isoformat()
                    local_conn.execute(
                        '''
                            INSERT INTO leave_balance_history
                            (id, employee_id, balance_type, change_type, change_amount,
                             previous_balance, new_balance, reason, application_id,
                             changed_by, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            str(uuid.uuid4()),
                            employee_id,
                            'PRIVILEGE',
                            'UNPAID',
                            unpaid_days,
                            remaining_snapshot,
                            remaining_snapshot,
                            'Unpaid remainder recorded for leave-without-pay application',
                            application_id,
                            changed_by,
                            current_time,
                        ),
                    )

                if created_connection:
                    local_conn.commit()
        except Exception:
            if created_connection:
                local_conn.rollback()
            raise
        finally:
            if created_connection:
                local_conn.close()

    with _lock_context():
        connection = conn or get_db_connection()
        try:
            cursor = connection.execute(
                'SELECT employee_id, leave_type, total_days, total_hours FROM leave_applications WHERE id = ?',
                (application_id,),
            )
            application = cursor.fetchone()
            if not application:
                raise ValueError(f"Leave application {application_id} not found")

            employee_id = application['employee_id']
            leave_type = application['leave_type']
            raw_days = application['total_days']
            raw_hours = application['total_hours']
            if raw_days is not None:
                total_days = float(raw_days)
            elif raw_hours is not None:
                total_days = float(raw_hours) / WORK_HOURS_PER_DAY if WORK_HOURS_PER_DAY else 0.0
            else:
                total_days = 0.0

            leave_token = (leave_type or '').strip().lower()
            is_leave_without_pay = leave_token == 'leave-without-pay'
            is_non_deductible = leave_token in NON_DEDUCTIBLE_LEAVE_TYPES and not is_leave_without_pay
            is_cash_out = leave_token == 'cash-out'

            if not is_non_deductible:
                balance_type = (
                    'PRIVILEGE'
                    if leave_token in PRIVILEGE_LEAVE_TYPES or is_leave_without_pay
                    else 'SICK'
                )

                cursor = connection.execute(
                    'SELECT id, remaining_days FROM leave_balances WHERE employee_id = ? AND balance_type = ? AND year = ?',
                    (employee_id, balance_type, current_year),
                )
                balance_exists = cursor.fetchone()
                if balance_exists and balance_type == 'PRIVILEGE':
                    privilege_remaining = float(balance_exists['remaining_days'])

            cursor = connection.execute(
                '''
                    SELECT change_type FROM leave_balance_history
                    WHERE application_id = ? AND change_type IN ('DEDUCTION', 'ADDITION')
                    ORDER BY created_at DESC LIMIT 1
                ''',
                (application_id,),
            )
            last_action = cursor.fetchone()

            cursor = connection.execute(
                '''
                    SELECT change_amount, balance_type
                    FROM leave_balance_history
                    WHERE application_id = ? AND change_type = 'DEDUCTION'
                    ORDER BY created_at DESC LIMIT 1
                ''',
                (application_id,),
            )
            last_deduction_entry = cursor.fetchone()
        finally:
            if conn is None:
                connection.close()

    if is_non_deductible:
        return True

    if not balance_exists:
        initialize_employee_balances(employee_id, current_year)

    if balance_type == 'PRIVILEGE' and privilege_remaining is None:
        _fetch_privilege_remaining()

    previous_privilege_balance = privilege_remaining if privilege_remaining is not None else 0.0

    reason = f"Leave application status changed to {new_status}"

    conn_for_update = conn if using_external_conn else None
    lock_for_update = lock if using_external_conn else None

    if new_status == 'Approved':
        if not last_action or last_action['change_type'] != 'DEDUCTION':
            deduction_days = total_days
            if is_leave_without_pay:
                available_days = max(previous_privilege_balance, 0.0)
                deduction_days = min(total_days, available_days)

            if deduction_days > 1e-6:
                update_leave_balance(
                    employee_id,
                    balance_type,
                    deduction_days,
                    reason,
                    application_id=application_id,
                    changed_by=changed_by,
                    prevent_negative=is_cash_out,
                    conn=conn_for_update,
                    lock=lock_for_update,
                )

            if is_leave_without_pay:
                unpaid_days = max(0.0, total_days - deduction_days)
                remaining_after_deduction = max(previous_privilege_balance - deduction_days, 0.0)
                _record_unpaid_history(unpaid_days, remaining_after_deduction)
    else:
        if last_action and last_action['change_type'] == 'DEDUCTION':
            deduction_to_reverse = total_days
            if is_leave_without_pay and last_deduction_entry:
                deduction_to_reverse = float(last_deduction_entry['change_amount'] or 0.0)

            if deduction_to_reverse > 1e-6:
                update_leave_balance(
                    employee_id,
                    balance_type,
                    -deduction_to_reverse,
                    reason,
                    application_id=application_id,
                    changed_by=changed_by,
                    prevent_negative=is_cash_out,
                    conn=conn_for_update,
                    lock=lock_for_update,
                )

            if is_leave_without_pay:
                _record_unpaid_history(0.0)

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

# Reset all balances for active employees
def reset_all_balances(year=None):
    """Reset leave balances for all active employees"""
    if year is None:
        year = datetime.now().year

    current_time = datetime.now().isoformat()

    with db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.execute('SELECT id FROM employees WHERE is_active = 1')
            employees = [row['id'] for row in cursor.fetchall()]

            for emp_id in employees:
                for balance_type, allocation in (
                    ('PRIVILEGE', DEFAULT_PRIVILEGE_LEAVE),
                    ('SICK', DEFAULT_SICK_LEAVE),
                ):
                    prev_cursor = conn.execute(
                        'SELECT remaining_days FROM leave_balances WHERE employee_id = ? AND balance_type = ? AND year = ?',
                        (emp_id, balance_type, year),
                    )
                    prev_row = prev_cursor.fetchone()
                    previous = prev_row['remaining_days'] if prev_row else 0

                    conn.execute(
                        '''
                        INSERT INTO leave_balances
                        (id, employee_id, balance_type, allocated_days, used_days, remaining_days,
                         carryforward_days, year, last_updated, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                        ON CONFLICT(employee_id, balance_type, year) DO UPDATE SET
                            allocated_days=excluded.allocated_days,
                            used_days=excluded.used_days,
                            remaining_days=excluded.remaining_days,
                            carryforward_days=excluded.carryforward_days,
                            last_updated=excluded.last_updated
                        ''',
                        (
                            str(uuid.uuid4()),
                            emp_id,
                            balance_type,
                            allocation,
                            0,
                            allocation,
                            year,
                            current_time,
                            current_time,
                        ),
                    )

                    if ENABLE_BALANCE_AUDIT:
                        conn.execute(
                            '''
                            INSERT INTO leave_balance_history
                            (id, employee_id, balance_type, change_type, change_amount,
                             previous_balance, new_balance, reason, application_id,
                             changed_by, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''',
                            (
                                str(uuid.uuid4()),
                                emp_id,
                                balance_type,
                                'RESET',
                                allocation,
                                previous,
                                allocation,
                                'Yearly balance reset',
                                None,
                                'SYSTEM',
                                current_time,
                            ),
                        )

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    return True

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
