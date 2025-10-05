import uuid

import pytest

from services import balance_manager, database_service, employee_service
from services.database_service import db_lock, get_db_connection

import server


@pytest.fixture
def test_database(tmp_path):
    original_db_path = database_service.DATABASE_PATH
    test_db_path = tmp_path / 'cash_out_test.db'
    database_service.DATABASE_PATH = str(test_db_path)
    database_service.init_database()
    try:
        yield
    finally:
        database_service.DATABASE_PATH = original_db_path


def _create_employee_with_balance(annual_leave):
    employee = employee_service.create_employee(
        {
            'first_name': 'Cash',
            'surname': 'Out',
            'personal_email': f'cash.out.{uuid.uuid4().hex[:6]}@example.com',
            'annual_leave': annual_leave,
            'sick_leave': 5,
        }
    )
    employee_id = employee['id']
    balance_manager.initialize_employee_balances(employee_id)
    return employee_id


def _fetch_remaining_vacation_days(employee_id):
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


def test_cash_out_submission_rejected_when_request_exceeds_balance(test_database):
    employee_id = _create_employee_with_balance(annual_leave=1)

    with pytest.raises(ValueError) as excinfo:
        server.ensure_cash_out_balance(employee_id, requested_days=2.0, requested_hours=16.0, preferred_unit='days')

    assert 'exceeds remaining Vacation Leave (VL)' in str(excinfo.value)
    assert pytest.approx(_fetch_remaining_vacation_days(employee_id)) == 1.0


def test_cash_out_approval_does_not_allow_negative_balance(test_database):
    employee_id = _create_employee_with_balance(annual_leave=1)
    application_id = str(uuid.uuid4())

    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute(
                '''
                INSERT INTO leave_applications (
                    id, application_id, employee_id, employee_name, start_date, end_date,
                    start_time, end_time, start_day_type, end_day_type, leave_type,
                    selected_reasons, reason, total_hours, total_days, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    application_id,
                    f'APP-{uuid.uuid4().hex[:8]}',
                    employee_id,
                    'Cash Out',
                    '2024-01-01',
                    '2024-01-01',
                    None,
                    None,
                    'full',
                    'full',
                    'cash-out',
                    '[]',
                    'Requesting more than available',
                    0.0,
                    2.0,
                    'Pending',
                ),
            )
            conn.commit()
        finally:
            conn.close()

    with pytest.raises(ValueError) as excinfo:
        balance_manager.process_leave_application_balance(application_id, 'Approved', changed_by='TEST')

    assert 'Insufficient Vacation Leave (VL) balance' in str(excinfo.value)
    assert pytest.approx(_fetch_remaining_vacation_days(employee_id)) == 1.0
