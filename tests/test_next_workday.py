import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pytest

from server import next_workday


def test_next_workday_skips_weekends():
    # Friday -> following Monday
    result = next_workday("2023-07-14", set())
    assert result == "2023-07-17"


def test_next_workday_respects_holidays():
    # Monday with Tuesday holiday -> Wednesday
    holidays = {"2023-07-18"}
    result = next_workday("2023-07-17", holidays)
    assert result == "2023-07-19"


def test_next_workday_invalid_input_returns_none():
    assert next_workday("invalid", set()) is None
    assert next_workday("", set()) is None
