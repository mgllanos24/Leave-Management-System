import uuid
from datetime import datetime

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


def _create_employee_with_vacation_balance():
    employee = employee_service.create_employee(
        {
            'first_name': 'Vacation',
            'surname': 'Saver',
            'personal_email': f'vacation.saver.{uuid.uuid4().hex[:6]}@example.com',
            'annual_leave': 10,
            'sick_leave': 5,
        }
    )
    employee_id = employee['id']
    balance_manager.initialize_employee_balances(employee_id)
    return employee_id


def _fetch_vacation_remaining_days(employee_id):
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


def test_leave_without_pay_rejected_when_request_within_vacation_balance(test_database):
    employee_id = _create_employee_with_vacation_balance()

    with pytest.raises(ValueError) as excinfo:
        server.ensure_leave_without_pay_allowed(employee_id, requested_days=1)

    assert str(excinfo.value) == server.LEAVE_WITHOUT_PAY_VACATION_MESSAGE
    assert _fetch_vacation_remaining_days(employee_id) > 0


def test_leave_without_pay_rejected_when_request_exceeds_vacation_balance(test_database):
    employee_id = _create_employee_with_vacation_balance()
    remaining = _fetch_vacation_remaining_days(employee_id)

    # Requesting more than the remaining balance must still be rejected when
    # any Vacation Leave (VL) remains.
    with pytest.raises(ValueError) as excinfo:
        server.ensure_leave_without_pay_allowed(
            employee_id,
            requested_days=remaining + 1,
        )

    assert str(excinfo.value) == server.LEAVE_WITHOUT_PAY_VACATION_MESSAGE


def test_leave_without_pay_uses_current_year_balance(test_database):
    """Vacation balances prefer the current year when multiple records exist."""

    employee_id = _create_employee_with_vacation_balance()
    current_year = datetime.now().year
    previous_year = current_year - 1

    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute(
                'UPDATE leave_balances SET remaining_days = 0, used_days = allocated_days '
                'WHERE employee_id = ? AND balance_type = "PRIVILEGE" AND year = ?',
                (employee_id, current_year),
            )
            conn.execute(
                (
                    """
                    INSERT INTO leave_balances (
                        id, employee_id, balance_type, allocated_days, used_days,
                        remaining_days, carryforward_days, year
                    ) VALUES (?, ?, 'PRIVILEGE', ?, ?, ?, 0, ?)
                    ON CONFLICT(employee_id, balance_type, year) DO UPDATE SET
                        allocated_days=excluded.allocated_days,
                        used_days=excluded.used_days,
                        remaining_days=excluded.remaining_days
                    """
                ),
                (
                    str(uuid.uuid4()),
                    employee_id,
                    15,
                    10,
                    5,
                    previous_year,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # Request within the previous year's balance should still be allowed because
    # the current year's Vacation Leave (VL) allocation is exhausted.
    server.ensure_leave_without_pay_allowed(employee_id, requested_days=1)
