import uuid

from services import balance_manager, database_service, employee_service


def test_leave_without_pay_partially_deducts_privilege_leave(tmp_path):
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
                'annual_leave': 5,
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

        def fetch_history():
            conn = database_service.get_db_connection()
            try:
                cursor = conn.execute(
                    'SELECT change_type, change_amount, previous_balance, new_balance, balance_type FROM leave_balance_history WHERE application_id = ? ORDER BY created_at',
                    (application_id,),
                )
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

        initial_balances = fetch_balances()
        initial_privilege = initial_balances['PRIVILEGE']

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
                        7.0,
                        'Pending',
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        balance_manager.process_leave_application_balance(application_id, 'Approved', changed_by='TEST')
        after_approval = fetch_balances()
        privilege_after = after_approval['PRIVILEGE']

        assert abs(privilege_after['used'] - (initial_privilege['used'] + 5.0)) < 1e-6
        assert abs(privilege_after['remaining'] - (initial_privilege['remaining'] - 5.0)) < 1e-6

        history_after_approval = fetch_history()
        deduction_entries = [h for h in history_after_approval if h['change_type'] == 'DEDUCTION']
        unpaid_entries = [h for h in history_after_approval if h['change_type'] == 'UNPAID']

        assert deduction_entries, 'Expected a deduction entry for leave-without-pay approval'
        assert unpaid_entries, 'Expected an unpaid entry for leave-without-pay approval'
        assert abs(deduction_entries[-1]['change_amount'] - 5.0) < 1e-6
        assert deduction_entries[-1]['balance_type'] == 'PRIVILEGE'
        assert abs(unpaid_entries[-1]['change_amount'] - 2.0) < 1e-6

        balance_manager.process_leave_application_balance(application_id, 'Rejected', changed_by='TEST')
        after_rejection = fetch_balances()

        assert abs(after_rejection['PRIVILEGE']['used'] - initial_privilege['used']) < 1e-6
        assert abs(after_rejection['PRIVILEGE']['remaining'] - initial_privilege['remaining']) < 1e-6

        history_after_rejection = fetch_history()
        unpaid_after_rejection = [h for h in history_after_rejection if h['change_type'] == 'UNPAID']
        addition_entries = [h for h in history_after_rejection if h['change_type'] == 'ADDITION']

        assert not unpaid_after_rejection
        assert addition_entries and abs(addition_entries[-1]['change_amount'] - 5.0) < 1e-6
    finally:
        database_service.DATABASE_PATH = original_db_path


def test_cash_out_counts_as_privilege_leave(tmp_path):
    original_db_path = database_service.DATABASE_PATH
    test_db_path = tmp_path / 'test_cash_out_privilege.db'
    database_service.DATABASE_PATH = str(test_db_path)

    try:
        database_service.init_database()

        employee = employee_service.create_employee(
            {
                'first_name': 'Cash',
                'surname': 'Out',
                'personal_email': 'cash.out@example.com',
                'annual_leave': 12,
                'sick_leave': 6,
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

        total_days = 2.5

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
                        'Cash Out',
                        '2024-02-01',
                        '2024-02-01',
                        None,
                        None,
                        'full',
                        'full',
                        'cash-out',
                        '',
                        '',
                        0.0,
                        total_days,
                        'Pending',
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        balance_manager.process_leave_application_balance(application_id, 'Approved', changed_by='TEST')
        after_approval = fetch_balances()

        privilege_initial = initial_balances['PRIVILEGE']
        privilege_after = after_approval['PRIVILEGE']

        assert privilege_after['used'] == privilege_initial['used'] + total_days
        assert privilege_after['remaining'] == privilege_initial['remaining'] - total_days

        balance_manager.process_leave_application_balance(application_id, 'Rejected', changed_by='TEST')
        after_rejection = fetch_balances()

        assert after_rejection == initial_balances
    finally:
        database_service.DATABASE_PATH = original_db_path


def test_leave_status_updates_share_transaction(tmp_path):
    original_db_path = database_service.DATABASE_PATH
    test_db_path = tmp_path / 'test_leave_status_updates_share_transaction.db'
    database_service.DATABASE_PATH = str(test_db_path)

    try:
        database_service.init_database()

        employee = employee_service.create_employee(
            {
                'first_name': 'Share',
                'surname': 'Transaction',
                'personal_email': 'share.transaction@example.com',
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

        def fetch_status():
            conn = database_service.get_db_connection()
            try:
                cursor = conn.execute(
                    'SELECT status FROM leave_applications WHERE id = ?',
                    (application_id,),
                )
                row = cursor.fetchone()
                return row['status'] if row else None
            finally:
                conn.close()

        initial_balances = fetch_balances()

        application_id = str(uuid.uuid4())
        public_application_id = str(uuid.uuid4())
        total_days = 1.5

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
                        'Share Transaction',
                        '2024-03-01',
                        '2024-03-02',
                        None,
                        None,
                        'full',
                        'full',
                        'vacation-annual',
                        '',
                        '',
                        0.0,
                        total_days,
                        'Pending',
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        # Approve within a shared transaction/connection context
        with database_service.db_lock:
            conn = database_service.get_db_connection()
            try:
                conn.execute(
                    'UPDATE leave_applications SET status = ? WHERE id = ?',
                    ('Approved', application_id),
                )
                balance_manager.process_leave_application_balance(
                    application_id,
                    'Approved',
                    changed_by='TEST',
                    conn=conn,
                )
                conn.commit()
            finally:
                conn.close()

        after_approval = fetch_balances()
        privilege_initial = initial_balances['PRIVILEGE']
        privilege_after = after_approval['PRIVILEGE']

        assert privilege_after['used'] == privilege_initial['used'] + total_days
        assert privilege_after['remaining'] == privilege_initial['remaining'] - total_days
        assert fetch_status() == 'Approved'

        # Reject within a shared transaction/connection context
        with database_service.db_lock:
            conn = database_service.get_db_connection()
            try:
                conn.execute(
                    'UPDATE leave_applications SET status = ? WHERE id = ?',
                    ('Rejected', application_id),
                )
                balance_manager.process_leave_application_balance(
                    application_id,
                    'Rejected',
                    changed_by='TEST',
                    conn=conn,
                )
                conn.commit()
            finally:
                conn.close()

        after_rejection = fetch_balances()

        assert after_rejection == initial_balances
        assert fetch_status() == 'Rejected'
    finally:
        database_service.DATABASE_PATH = original_db_path
