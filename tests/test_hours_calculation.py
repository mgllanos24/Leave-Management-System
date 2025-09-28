import math

from server import WORK_HOURS_PER_DAY, calculate_total_days, calculate_total_hours


def test_multi_day_request_is_capped_per_day():
    hours = calculate_total_hours(
        "2025-09-29",
        "2025-10-02",
        start_time="08:00",
        end_time="17:00",
    )
    assert math.isclose(hours, 32.0, rel_tol=0, abs_tol=1e-6)

    days = calculate_total_days(
        "2025-09-29",
        "2025-10-02",
        start_time="08:00",
        end_time="17:00",
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
