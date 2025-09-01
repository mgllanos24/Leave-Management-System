"""
Service: Database Service. Purpose: Handle all database operations and connections.
TODO: implement functions and add error handling.
"""

import sqlite3
import uuid
import threading
import os  # @tweakable missing import for file operations
from datetime import datetime

# Moved from server.py - database configuration and connection handling
# @tweakable database configuration parameters
DATABASE_PATH = "leave_management.db"
MAX_DB_RETRIES = 3
DB_CONNECTION_TIMEOUT = 30

# Database lock for thread safety
# Use RLock to allow the same thread to re-acquire the lock safely
db_lock = threading.RLock()

def get_db_connection():
    """Get database connection with retry logic"""
    for attempt in range(MAX_DB_RETRIES):
        try:
            conn = sqlite3.connect(DATABASE_PATH, timeout=DB_CONNECTION_TIMEOUT)
            conn.execute('PRAGMA foreign_keys = ON')
            conn.row_factory = sqlite3.Row  # Enable dict-like access
            return conn
        except sqlite3.Error as e:
            if attempt == MAX_DB_RETRIES - 1:
                raise e
    return None

def init_database():
    """Initialize SQLite database with required tables"""
    # @tweakable database backup configuration
    CREATE_DB_BACKUP = True
    
    if CREATE_DB_BACKUP and os.path.exists(DATABASE_PATH):
        backup_path = f"{DATABASE_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        import shutil
        shutil.copy2(DATABASE_PATH, backup_path)
        print(f"📦 Database backup created: {backup_path}")
    
    conn = sqlite3.connect(DATABASE_PATH, timeout=DB_CONNECTION_TIMEOUT)
    conn.execute('PRAGMA foreign_keys = ON')
    
    # Create all required tables
    _create_tables(conn)
    _create_indexes(conn)
    
    conn.commit()
    conn.close()

def _create_tables(conn):
    """Create all database tables"""
    # @tweakable employee table configuration
    MAX_FIRSTNAME_LENGTH = 50
    MAX_SURNAME_LENGTH = 50
    DEFAULT_PRIVILEGE_LEAVE = 15
    DEFAULT_SICK_LEAVE = 7
    
    # Create employees table with enhanced structure
    conn.execute(f'''
        CREATE TABLE IF NOT EXISTS employees (
            id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL CHECK(length(first_name) <= {MAX_FIRSTNAME_LENGTH}),
            surname TEXT NOT NULL CHECK(length(surname) <= {MAX_SURNAME_LENGTH}),
            personal_email TEXT UNIQUE NOT NULL,
            annual_leave INTEGER DEFAULT {DEFAULT_PRIVILEGE_LEAVE} CHECK(annual_leave >= 0),
            sick_leave INTEGER DEFAULT {DEFAULT_SICK_LEAVE} CHECK(sick_leave >= 0),
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create other tables...
    _create_leave_tables(conn)
    _create_balance_tables(conn)
    _create_notification_tables(conn)

def _create_leave_tables(conn):
    """Create leave-related tables"""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS leave_applications (
            id TEXT PRIMARY KEY,
            application_id TEXT UNIQUE NOT NULL,
            employee_id TEXT NOT NULL,
            employee_name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            start_day_type TEXT DEFAULT 'full',
            end_day_type TEXT DEFAULT 'full',
            leave_type TEXT NOT NULL,
            selected_reasons TEXT,
            reason TEXT,
            total_days REAL NOT NULL,
            status TEXT DEFAULT 'Pending',
            date_applied TEXT DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS holidays (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

def _create_balance_tables(conn):
    """Create balance tracking tables"""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS leave_balances (
            id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            balance_type TEXT NOT NULL,
            allocated_days REAL NOT NULL DEFAULT 0,
            used_days REAL NOT NULL DEFAULT 0,
            remaining_days REAL NOT NULL DEFAULT 0,
            carryforward_days REAL DEFAULT 0,
            year INTEGER NOT NULL,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE,
            UNIQUE(employee_id, balance_type, year)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS leave_balance_history (
            id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            balance_type TEXT NOT NULL,
            change_type TEXT NOT NULL,
            change_amount REAL NOT NULL,
            previous_balance REAL NOT NULL,
            new_balance REAL NOT NULL,
            reason TEXT,
            application_id TEXT,
            changed_by TEXT DEFAULT 'SYSTEM',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE,
            FOREIGN KEY (application_id) REFERENCES leave_applications (id) ON DELETE SET NULL
        )
    ''')

def _create_notification_tables(conn):
    """Create notification tables"""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            message TEXT NOT NULL,
            read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE
        )
    ''')

def _create_indexes(conn):
    """Create database indexes for better performance"""
    # Employee indexes
    conn.execute('CREATE INDEX IF NOT EXISTS idx_employees_email ON employees(personal_email)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_employees_active ON employees(is_active)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_employees_name ON employees(first_name, surname)')
    
    # Balance indexes
    conn.execute('CREATE INDEX IF NOT EXISTS idx_leave_balances_employee ON leave_balances(employee_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_leave_balances_year ON leave_balances(year)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_balance_history_employee ON leave_balance_history(employee_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_balance_history_date ON leave_balance_history(created_at)')


def _todo():
    """Placeholder to keep the module importable."""
    return None
