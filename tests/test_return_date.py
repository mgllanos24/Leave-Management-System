from server import LATEST_LEAVE_TIME, WORK_HOURS_PER_DAY, compute_return_date


def test_partial_day_before_end_of_day_returns_same_day():
    same_day_return = compute_return_date("2025-12-17", WORK_HOURS_PER_DAY / 2, "10:00")
    assert same_day_return == "2025-12-17"


def test_partial_day_ending_at_close_returns_next_workday():
    next_day_return = compute_return_date("2025-12-17", 1.5, LATEST_LEAVE_TIME.strftime("%H:%M"))
    assert next_day_return == "2025-12-18"


def test_partial_day_ending_at_close_skips_holidays():
    holidays = {"2025-12-18"}
    next_workday = compute_return_date(
        "2025-12-17",
        1.5,
        LATEST_LEAVE_TIME.strftime("%H:%M"),
        holidays,
    )
    assert next_workday == "2025-12-19"
