import uuid

from services import balance_manager, database_service, employee_service


def test_leave_without_pay_does_not_adjust_balances(tmp_path):
    original_db_path = database_service.DATABASE_PATH
    test_db_path = tmp_path / 'test_leave_without_pay.db'
    database_service.DATABASE_PATH = str(test_db_path)

    try:
        database_service.init_database()

        employee = employee_service.create_employee(
            {
                'first_name': 'Test',
                'surname': 'User',
                'personal_email': 'test.user@example.com',
                'annual_leave': 10,
                'sick_leave': 5,
            }
        )

        employee_id = employee['id']
        balance_manager.initialize_employee_balances(employee_id)

        def fetch_balances():
            conn = database_service.get_db_connection()
            try:
                cursor = conn.execute(
                    'SELECT balance_type, used_days, remaining_days FROM leave_balances WHERE employee_id = ?',
                    (employee_id,),
                )
                return {
                    row['balance_type']: {
                        'used': row['used_days'],
                        'remaining': row['remaining_days'],
                    }
                    for row in cursor.fetchall()
                }
            finally:
                conn.close()

        initial_balances = fetch_balances()

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
                        'Test User',
                        '2024-01-01',
                        '2024-01-01',
                        None,
                        None,
                        'full',
                        'full',
                        'leave-without-pay',
                        '',
                        '',
                        0.0,
                        1.0,
                        'Pending',
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        balance_manager.process_leave_application_balance(application_id, 'Approved', changed_by='TEST')
        after_approval = fetch_balances()

        assert after_approval == initial_balances

        balance_manager.process_leave_application_balance(application_id, 'Rejected', changed_by='TEST')
        after_rejection = fetch_balances()

        assert after_rejection == initial_balances
    finally:
        database_service.DATABASE_PATH = original_db_path
