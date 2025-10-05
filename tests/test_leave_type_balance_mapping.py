import uuid

import pytest

from services import balance_manager, database_service, employee_service


def _create_leave_application(employee_id, leave_type, total_days):
    application_id = str(uuid.uuid4())
    public_application_id = str(uuid.uuid4())

    with database_service.db_lock:
        conn = database_service.get_db_connection()
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
                    public_application_id,
                    employee_id,
                    'Type Tester',
                    '2024-01-01',
                    '2024-01-01',
                    None,
                    None,
                    'full',
                    'full',
                    leave_type,
                    '',
                    '',
                    0.0,
                    float(total_days),
                    'Pending',
                ),
            )
            conn.commit()
        finally:
            conn.close()

    return application_id


def _fetch_balances(employee_id):
    conn = database_service.get_db_connection()
    try:
        cursor = conn.execute(
            'SELECT balance_type, used_days, remaining_days FROM leave_balances WHERE employee_id = ?',
            (employee_id,),
        )
        return {
            row['balance_type']: {
                'used': float(row['used_days']),
                'remaining': float(row['remaining_days']),
            }
            for row in cursor.fetchall()
        }
    finally:
        conn.close()


@pytest.mark.parametrize(
    ('leave_type', 'expected_balance_type'),
    [
        ('personal', 'PRIVILEGE'),
        ('vacation-annual', 'PRIVILEGE'),
        ('cash-out', 'PRIVILEGE'),
        ('family-emergency', 'PRIVILEGE'),
        ('bereavement', 'PRIVILEGE'),
        ('maternity-paternity', 'PRIVILEGE'),
        ('study-exam', 'PRIVILEGE'),
        ('childcare', 'PRIVILEGE'),
        ('jury-duty', 'PRIVILEGE'),
        ('leave-without-pay', 'PRIVILEGE'),
        ('other', 'PRIVILEGE'),
        ('sick', 'SICK'),
        ('medical-appointment', 'SICK'),
    ],
)
def test_leave_type_routes_to_correct_balance(tmp_path, leave_type, expected_balance_type):
    original_db_path = database_service.DATABASE_PATH
    database_service.DATABASE_PATH = str(tmp_path / f'{leave_type}_mapping.db')

    try:
        database_service.init_database()

        employee = employee_service.create_employee(
            {
                'first_name': 'Type',
                'surname': 'Tester',
                'personal_email': 'type.tester@example.com',
                'annual_leave': 10,
                'sick_leave': 8,
            }
        )

        employee_id = employee['id']
        balance_manager.initialize_employee_balances(employee_id)

        initial_balances = _fetch_balances(employee_id)

        application_id = _create_leave_application(employee_id, leave_type, total_days=1)

        balance_manager.process_leave_application_balance(
            application_id, 'Approved', changed_by='TEST'
        )

        updated_balances = _fetch_balances(employee_id)

        privilege_initial = initial_balances['PRIVILEGE']
        privilege_updated = updated_balances['PRIVILEGE']
        sick_initial = initial_balances['SICK']
        sick_updated = updated_balances['SICK']

        if expected_balance_type == 'PRIVILEGE':
            assert privilege_updated['used'] == pytest.approx(privilege_initial['used'] + 1.0)
            assert privilege_updated['remaining'] == pytest.approx(
                privilege_initial['remaining'] - 1.0
            )
            assert sick_updated['used'] == pytest.approx(sick_initial['used'])
            assert sick_updated['remaining'] == pytest.approx(sick_initial['remaining'])
        else:
            assert sick_updated['used'] == pytest.approx(sick_initial['used'] + 1.0)
            assert sick_updated['remaining'] == pytest.approx(sick_initial['remaining'] - 1.0)
            assert privilege_updated['used'] == pytest.approx(privilege_initial['used'])
            assert privilege_updated['remaining'] == pytest.approx(
                privilege_initial['remaining']
            )
    finally:
        database_service.DATABASE_PATH = original_db_path
