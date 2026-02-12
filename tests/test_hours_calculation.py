import math

import pytest

from server import WORK_HOURS_PER_DAY, calculate_total_days, calculate_total_hours


def test_multi_day_request_is_capped_per_day():
    hours = calculate_total_hours(
        "2025-09-29",
        "2025-10-02",
        start_time="06:30",
        end_time="15:00",
    )
    assert math.isclose(hours, 32.0, rel_tol=0, abs_tol=1e-6)

    days = calculate_total_days(
        "2025-09-29",
        "2025-10-02",
        start_time="06:30",
        end_time="15:00",
    )
    assert math.isclose(days, 4.0, rel_tol=0, abs_tol=1e-6)
    assert hours == WORK_HOURS_PER_DAY * days


def test_multi_day_request_ignores_time_offsets():
    hours = calculate_total_hours(
        "2025-09-29",
        "2025-09-30",
        start_time="15:00",
        end_time="09:00",
    )

    assert math.isclose(hours, WORK_HOURS_PER_DAY * 2, rel_tol=0, abs_tol=1e-6)


def test_single_day_accepts_boundary_times():
    hours = calculate_total_hours(
        "2025-09-30",
        "2025-09-30",
        start_time="06:30",
        end_time="15:00",
    )
    assert math.isclose(hours, WORK_HOURS_PER_DAY, rel_tol=0, abs_tol=1e-6)

    days = calculate_total_days(
        "2025-09-30",
        "2025-09-30",
        start_time="06:30",
        end_time="15:00",
    )
    assert math.isclose(days, 1.0, rel_tol=0, abs_tol=1e-6)


def test_single_day_rejects_start_before_window():
    with pytest.raises(ValueError) as error_info:
        calculate_total_hours(
            "2025-09-30",
            "2025-09-30",
            start_time="06:29",
            end_time="15:00",
        )

    assert "06:30" in str(error_info.value)


def test_single_day_rejects_end_after_window():
    with pytest.raises(ValueError) as error_info:
        calculate_total_hours(
            "2025-09-30",
            "2025-09-30",
            start_time="06:30",
            end_time="15:01",
        )

    assert "15:00" in str(error_info.value)


def test_rejects_end_date_before_start_date():
    with pytest.raises(ValueError) as error_info:
        calculate_total_hours(
            "2026-02-13",
            "2026-02-02",
            start_time="06:30",
            end_time="15:00",
        )

    assert "on or after the start date" in str(error_info.value)
