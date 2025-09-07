import sys
from pathlib import Path

import pytest

# Ensure the services package is importable
sys.path.append(str(Path(__file__).resolve().parents[1]))
from services import database_service


def test_get_db_connection_failure(tmp_path, monkeypatch):
    # Use a path in a non-existent directory to force connection failure
    invalid_db_path = tmp_path / "nonexistent" / "db.sqlite"
    monkeypatch.setattr(database_service, "DATABASE_PATH", str(invalid_db_path))
    with pytest.raises(ConnectionError):
        database_service.get_db_connection()

