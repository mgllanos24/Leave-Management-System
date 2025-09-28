import uuid

import pytest

from services import balance_manager, database_service, employee_service
from services.database_service import db_lock, get_db_connection

import server


@pytest.fixture
def test_database(tmp_path):
    original_db_path = database_service.DATABASE_PATH
    test_db_path = tmp_path / 'leave_without_pay_validation.db'
    database_service.DATABASE_PATH = str(test_db_path)
    database_service.init_database()
    try:
        yield
    finally:
        database_service.DATABASE_PATH = original_db_path


def _create_employee_with_privilege_balance():
    employee = employee_service.create_employee(
        {
            'first_name': 'Privilege',
            'surname': 'Saver',
            'personal_email': f'privilege.saver.{uuid.uuid4().hex[:6]}@example.com',
            'annual_leave': 10,
            'sick_leave': 5,
        }
    )
    employee_id = employee['id']
    balance_manager.initialize_employee_balances(employee_id)
    return employee_id


def _fetch_privilege_remaining_days(employee_id):
    with db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.execute(
                'SELECT remaining_days FROM leave_balances '
                'WHERE employee_id = ? AND balance_type = "PRIVILEGE"',
                (employee_id,),
            )
            row = cursor.fetchone()
            return float(row['remaining_days']) if row else 0.0
        finally:
            conn.close()


def test_leave_without_pay_rejected_when_request_within_privilege_balance(test_database):
    employee_id = _create_employee_with_privilege_balance()

    with pytest.raises(ValueError) as excinfo:
        server.ensure_leave_without_pay_allowed(employee_id, requested_days=1)

    assert str(excinfo.value) == server.LEAVE_WITHOUT_PAY_PRIVILEGE_MESSAGE
    assert _fetch_privilege_remaining_days(employee_id) > 0


def test_leave_without_pay_allowed_when_request_exceeds_privilege_balance(test_database):
    employee_id = _create_employee_with_privilege_balance()
    remaining = _fetch_privilege_remaining_days(employee_id)

    # Request more than the remaining balance should be permitted
    server.ensure_leave_without_pay_allowed(
        employee_id,
        requested_days=remaining + 1,
    )
