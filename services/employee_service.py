"""
Service: Employee Service. Purpose: Manage employee creation, updates, and queries.
TODO: implement functions and add error handling.
"""

from .database_service import get_db_connection, db_lock
from datetime import datetime
import uuid

# Moved from server.py - employee management functions
# @tweakable employee validation configuration
ENABLE_EMPLOYEE_VALIDATION = True
VALIDATE_EMAIL_UNIQUENESS = True
MAX_FIRSTNAME_LENGTH = 50
MAX_SURNAME_LENGTH = 50
DEFAULT_PRIVILEGE_LEAVE = 15
DEFAULT_SICK_LEAVE = 7
ENABLE_EMPLOYEE_AUDIT = True

def create_employee(employee_data):
    """Create a new employee record with validation"""
    with db_lock:
        conn = get_db_connection()
        try:
            record_id = str(uuid.uuid4())
            current_time = datetime.now().isoformat()
            
            # Enhanced employee validation
            if ENABLE_EMPLOYEE_VALIDATION:
                _validate_employee_data(conn, employee_data)
            
            conn.execute('''
                INSERT INTO employees (id, first_name, surname, personal_email, annual_leave, sick_leave, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            ''', (
                record_id,
                employee_data.get('first_name', '').strip(),
                employee_data.get('surname', '').strip(),
                employee_data.get('personal_email', '').strip().lower(),
                employee_data.get('annual_leave', DEFAULT_PRIVILEGE_LEAVE),
                employee_data.get('sick_leave', DEFAULT_SICK_LEAVE),
                current_time,
                current_time
            ))
            
            conn.commit()
            
            if ENABLE_EMPLOYEE_AUDIT:
                print(f"📝 Employee created: {employee_data.get('first_name')} {employee_data.get('surname')} ({employee_data.get('personal_email')})")
            
            # Return the created record
            created_record = dict(employee_data)
            created_record['id'] = record_id
            created_record['created_at'] = current_time
            
            return created_record
            
        finally:
            conn.close()

def update_employee(employee_id, employee_data):
    """Update an employee record with validation"""
    with db_lock:
        conn = get_db_connection()
        try:
            current_time = datetime.now().isoformat()
            
            # Enhanced employee update validation
            if ENABLE_EMPLOYEE_VALIDATION:
                _validate_employee_update_data(conn, employee_id, employee_data)
            
            conn.execute('''
                UPDATE employees 
                SET first_name=?, surname=?, personal_email=?, annual_leave=?, sick_leave=?, updated_at=?
                WHERE id=? AND is_active=1
            ''', (
                employee_data.get('first_name', '').strip(),
                employee_data.get('surname', '').strip(),
                employee_data.get('personal_email', '').strip().lower(),
                employee_data.get('annual_leave', DEFAULT_PRIVILEGE_LEAVE),
                employee_data.get('sick_leave', DEFAULT_SICK_LEAVE),
                current_time,
                employee_id
            ))
            
            if conn.total_changes == 0:
                raise ValueError("Employee not found or already inactive")
            
            conn.commit()
            
            if ENABLE_EMPLOYEE_AUDIT:
                print(f"📝 Employee updated: {employee_id}")
            
            return True
            
        finally:
            conn.close()

def delete_employee(employee_id):
    """Soft delete an employee (maintain data integrity)"""
    with db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.execute('UPDATE employees SET is_active = 0, updated_at = ? WHERE id = ? AND is_active = 1', 
                                (datetime.now().isoformat(), employee_id))
            
            if conn.total_changes == 0:
                raise ValueError("Employee not found or already inactive")
            
            conn.commit()
            
            if ENABLE_EMPLOYEE_AUDIT:
                print(f"📝 Employee soft deleted: {employee_id}")
            
            return True
            
        finally:
            conn.close()

def get_employees(active_only=True):
    """Get all employees with optional active filter"""
    conn = get_db_connection()
    try:
        if active_only:
            cursor = conn.execute('SELECT * FROM employees WHERE is_active = 1 ORDER BY created_at DESC')
        else:
            cursor = conn.execute('SELECT * FROM employees ORDER BY created_at DESC')
        
        results = [dict(row) for row in cursor.fetchall()]
        return results
        
    finally:
        conn.close()

def get_employee_by_email(email):
    """Get employee by email address"""
    conn = get_db_connection()
    try:
        cursor = conn.execute('SELECT * FROM employees WHERE personal_email = ? AND is_active = 1', (email.lower(),))
        result = cursor.fetchone()
        return dict(result) if result else None
        
    finally:
        conn.close()

def _validate_employee_data(conn, data):
    """Validate employee data before creation"""
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

def _validate_employee_update_data(conn, employee_id, data):
    """Validate employee data before update"""
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
        cursor = conn.execute('SELECT id FROM employees WHERE personal_email = ? AND id != ? AND is_active = 1', (email, employee_id))
        if cursor.fetchone():
            raise ValueError(f"Employee with email {email} already exists")

def _todo():
    """Placeholder to keep the module importable."""
    return None