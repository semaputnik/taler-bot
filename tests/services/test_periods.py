"""Period arithmetic: pure functions, no database."""

from datetime import date

import pytest

from src.services.periods import is_current, next_anchor, period, previous, previous_anchor


@pytest.mark.parametrize(
    ("anchor", "start", "end"),
    [
        (date(2026, 10, 14), date(2026, 10, 12), date(2026, 10, 19)),  # mid-week (Wednesday)
        (date(2026, 10, 12), date(2026, 10, 12), date(2026, 10, 19)),  # the Monday itself
        (date(2026, 10, 18), date(2026, 10, 12), date(2026, 10, 19)),  # a Sunday
        (date(2026, 10, 29), date(2026, 10, 26), date(2026, 11, 2)),  # a week across two months
        (date(2026, 12, 31), date(2026, 12, 28), date(2027, 1, 4)),  # a week across two years
    ],
)
def test_a_week_runs_from_monday_to_the_next_monday(anchor, start, end):
    assert period("week", anchor) == (start, end)


@pytest.mark.parametrize(
    ("anchor", "start", "end"),
    [
        (date(2026, 10, 14), date(2026, 10, 1), date(2026, 11, 1)),
        (date(2026, 10, 31), date(2026, 10, 1), date(2026, 11, 1)),  # the 31st
        (date(2026, 2, 28), date(2026, 2, 1), date(2026, 3, 1)),  # February
        (date(2028, 2, 29), date(2028, 2, 1), date(2028, 3, 1)),  # a leap February
        (date(2026, 12, 5), date(2026, 12, 1), date(2027, 1, 1)),  # the end of a year
    ],
)
def test_a_month_runs_from_the_first_to_the_next_first(anchor, start, end):
    assert period("month", anchor) == (start, end)


def test_the_previous_week_is_the_seven_days_before():
    assert previous(date(2026, 10, 12), date(2026, 10, 19)) == (
        date(2026, 10, 5),
        date(2026, 10, 12),
    )


def test_the_previous_week_crosses_a_year_boundary():
    assert previous(date(2027, 1, 4), date(2027, 1, 11)) == (date(2026, 12, 28), date(2027, 1, 4))


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (date(2026, 10, 1), (date(2026, 9, 1), date(2026, 10, 1))),  # a 30-day month back
        (date(2026, 3, 1), (date(2026, 2, 1), date(2026, 3, 1))),  # February, 28 days
        (date(2026, 1, 1), (date(2025, 12, 1), date(2026, 1, 1))),  # across the year
    ],
)
def test_the_previous_month_is_the_whole_month_before(current, expected):
    start, end = period("month", current)
    assert previous(start, end) == expected


def test_a_week_that_starts_on_the_25th_is_still_a_week():
    start, end = period("week", date(2026, 10, 26))
    assert previous(start, end) == (date(2026, 10, 19), date(2026, 10, 26))


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 11), False),
        (date(2026, 10, 12), True),  # the first day
        (date(2026, 10, 18), True),  # the last day
        (date(2026, 10, 19), False),  # end is exclusive
    ],
)
def test_a_period_is_current_when_today_is_inside_it(today, expected):
    assert is_current(date(2026, 10, 12), date(2026, 10, 19), today) is expected


def test_the_arrows_anchors_are_the_end_and_the_day_before_the_start():
    assert next_anchor(date(2026, 10, 1), date(2026, 11, 1)) == date(2026, 11, 1)
    assert previous_anchor(date(2026, 10, 1), date(2026, 11, 1)) == date(2026, 9, 30)
    assert previous_anchor(date(2026, 1, 1), date(2026, 2, 1)) == date(2025, 12, 31)
    assert period("month", previous_anchor(date(2026, 1, 1), date(2026, 2, 1))) == (
        date(2025, 12, 1),
        date(2026, 1, 1),
    )
