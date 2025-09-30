import io
import json
import sqlite3

import server


def test_leave_approval_uses_ooo_summary(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE leave_applications (
            id TEXT PRIMARY KEY,
            application_id TEXT,
            employee_id TEXT,
            employee_name TEXT,
            start_date TEXT,
            end_date TEXT,
            start_time TEXT,
            end_time TEXT,
            total_hours REAL,
            total_days REAL,
            status TEXT,
            leave_type TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE employees (
            id TEXT PRIMARY KEY,
            personal_email TEXT
        )
        """
    )
    conn.execute("CREATE TABLE holidays (date TEXT)")

    conn.execute(
        """
        INSERT INTO leave_applications (
            id, application_id, employee_id, employee_name,
            start_date, end_date, start_time, end_time,
            total_hours, total_days, status, leave_type, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "leave-1",
            "APP-001",
            "emp-1",
            "Alice Smith",
            "2024-06-01",
            "2024-06-02",
            "09:00",
            "17:00",
            16.0,
            2.0,
            "Pending",
            "Annual Leave",
            "2024-05-01T00:00:00",
        ),
    )
    conn.execute(
        "INSERT INTO employees (id, personal_email) VALUES (?, ?)",
        ("emp-1", "alice@example.com"),
    )
    conn.commit()

    monkeypatch.setattr(server, "get_db_connection", lambda: conn)
    monkeypatch.setattr(server, "process_leave_application_balance", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "send_notification_email", lambda *args, **kwargs: (True, None))

    captured_summary = {}

    def fake_generate_ics_content(*args, **kwargs):
        captured_summary["summary"] = kwargs.get("summary")
        return "BEGIN:VCALENDAR\r\nEND:VCALENDAR"

    monkeypatch.setattr(server, "generate_ics_content", fake_generate_ics_content)

    responses = []

    def fake_send_json_response(self, data, status=200):
        responses.append((data, status))

    monkeypatch.setattr(server.LeaveManagementHandler, "send_json_response", fake_send_json_response)

    errors = []

    def fake_send_error(self, code, message=None, explain=None):
        errors.append((code, message))

    monkeypatch.setattr(server.LeaveManagementHandler, "send_error", fake_send_error)

    handler = server.LeaveManagementHandler.__new__(server.LeaveManagementHandler)
    payload = json.dumps({"status": "Approved"}).encode("utf-8")
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    handler.wfile = io.BytesIO()
    handler.command = "PUT"
    handler.path = "/api/leave_application/leave-1"

    handler.handle_put_request("leave_application", ["", "api", "leave_application", "leave-1"])

    assert not errors, f"Unexpected errors during request: {errors}"
    assert captured_summary["summary"] == "Alice Smith - OOO"

    conn.close()

