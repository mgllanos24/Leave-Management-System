import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pytest

from services import database_service, employee_service


def setup_module(module):
    # Ensure validation is enabled for tests
    employee_service.ENABLE_EMPLOYEE_VALIDATION = True
    employee_service.VALIDATE_EMAIL_UNIQUENESS = True


def test_employee_reactivation(tmp_path):
    db_path = tmp_path / 'test.db'
    database_service.DATABASE_PATH = str(db_path)
    database_service.init_database()

    # Create and then soft delete an employee
    employee_data = {
        'first_name': 'John',
        'surname': 'Doe',
        'personal_email': 'john@example.com',
        'annual_leave': 10,
        'sick_leave': 2,
    }

    created = employee_service.create_employee(employee_data)
    employee_service.delete_employee(created['id'])

    # Reactivate with updated details
    new_data = {
        'first_name': 'Johnny',
        'surname': 'Doe',
        'personal_email': 'john@example.com',
        'annual_leave': 12,
        'sick_leave': 4,
    }

    reactivated = employee_service.create_employee(new_data)

    assert reactivated['id'] == created['id']
    assert reactivated['first_name'] == 'Johnny'
    assert reactivated['annual_leave'] == 12
    assert reactivated['is_active'] == 1

    # Ensure only one record exists with that email
    conn = database_service.get_db_connection()
    try:
        cursor = conn.execute('SELECT COUNT(*) as cnt FROM employees WHERE personal_email = ?', ('john@example.com',))
        assert cursor.fetchone()['cnt'] == 1
    finally:
        conn.close()

