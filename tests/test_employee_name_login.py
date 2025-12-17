import io
import json
import sqlite3

import server


def _prepare_employee_db():
    uri = "file:employee-login-test?mode=memory&cache=shared"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE employees (
            id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            surname TEXT NOT NULL,
            personal_email TEXT NOT NULL,
            annual_leave INTEGER DEFAULT 15,
            sick_leave INTEGER DEFAULT 7,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE leave_balances (
            id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            balance_type TEXT NOT NULL,
            year INTEGER,
            remaining_days REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return uri, conn


def test_employee_can_login_with_first_and_last_name(monkeypatch):
    uri, seed_connection = _prepare_employee_db()
    seed_connection.execute(
        "INSERT INTO employees (id, first_name, surname, personal_email, is_active) VALUES (?, ?, ?, ?, 1)",
        ("emp-123", "Mark", "Llanos", "mgllanos@yahoo.com"),
    )
    seed_connection.commit()

    monkeypatch.setattr(
        server,
        "get_db_connection",
        lambda: _connect_shared(uri),
    )
    monkeypatch.setattr(server, "initialize_employee_balances", lambda _employee_id: True)

    responses = []
    errors = []

    def fake_send_json_response(self, data, status=200):
        responses.append((data, status))

    def fake_send_error(self, code, message=None, explain=None):
        errors.append((code, message))

    handler = server.LeaveManagementHandler.__new__(server.LeaveManagementHandler)
    payload = json.dumps({"identifier": "Mark Llanos"}).encode("utf-8")
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    handler.wfile = io.BytesIO()

    monkeypatch.setattr(server.LeaveManagementHandler, "send_json_response", fake_send_json_response)
    monkeypatch.setattr(server.LeaveManagementHandler, "send_error", fake_send_error)

    handler.handle_bootstrap_employee()

    assert not errors, f"Unexpected errors during login: {errors}"
    assert responses, "No response recorded from bootstrap handler"
    response_data, status = responses[0]
    assert status == 200
    assert response_data["employee"]["first_name"] == "Mark"
    assert response_data["employee"]["surname"] == "Llanos"

    seed_connection.close()


def _connect_shared(uri: str):
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
