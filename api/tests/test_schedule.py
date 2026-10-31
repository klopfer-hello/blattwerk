"""Date logic of the to-do engine (pure): which occurrences a task has, and when."""

from datetime import date

import pytest

from garten_planer.schedule import Occurrence, TaskTiming, interval_after, months_in_year, occurrences, yearly_window

D = date


@pytest.mark.parametrize(
    ("year", "m_from", "m_to", "expected"),
    [
        (2026, 3, 3, (D(2026, 3, 1), D(2026, 3, 31))),
        (2026, 2, 2, (D(2026, 2, 1), D(2026, 2, 28))),
        (2028, 2, 2, (D(2028, 2, 1), D(2028, 2, 29))),  # leap year
        (2026, 10, 12, (D(2026, 10, 1), D(2026, 12, 31))),
        (2026, 11, 2, (D(2026, 11, 1), D(2027, 2, 28))),  # wraps the year end
    ],
)
def test_yearly_window(year: int, m_from: int, m_to: int, expected: tuple[date, date]) -> None:
    assert yearly_window(year, m_from, m_to) == expected


def yearly(m_from: int, m_to: int) -> TaskTiming:
    return TaskTiming(recurrence="yearly", month_from=m_from, month_to=m_to)


@pytest.mark.parametrize(
    ("timing", "today", "expected"),
    [
        # current window and the next one inside the 60-day horizon
        (yearly(11, 11), D(2026, 11, 2), [Occurrence("2026", D(2026, 11, 1), D(2026, 11, 30))]),
        (yearly(12, 12), D(2026, 11, 2), [Occurrence("2026", D(2026, 12, 1), D(2026, 12, 31))]),
        (yearly(3, 3), D(2026, 11, 2), []),  # too far ahead, already past this year
        (yearly(11, 2), D(2027, 1, 15), [Occurrence("2026", D(2026, 11, 1), D(2027, 2, 28))]),  # started last year
        (yearly(1, 1), D(2026, 12, 15), [Occurrence("2027", D(2027, 1, 1), D(2027, 1, 31))]),
        (
            TaskTiming(recurrence="once", due_date=D(2026, 11, 20)),
            D(2026, 11, 2),
            [Occurrence("once", D(2026, 11, 20), D(2026, 11, 20))],
        ),
        (TaskTiming(recurrence="once", due_date=D(2027, 6, 1)), D(2026, 11, 2), []),  # beyond the horizon
        (
            TaskTiming(recurrence="once", due_date=D(2026, 10, 1)),
            D(2026, 11, 2),
            [Occurrence("once", D(2026, 10, 1), D(2026, 10, 1))],
        ),  # overdue: still shown
        (
            TaskTiming(recurrence="interval", interval_days=7, start_date=D(2026, 11, 2)),
            D(2026, 11, 2),
            [Occurrence("2026-11-02", D(2026, 11, 2), D(2026, 11, 3))],
        ),
    ],
)
def test_occurrences(timing: TaskTiming, today: date, expected: list[Occurrence]) -> None:
    assert occurrences(timing, today) == expected


@pytest.mark.parametrize(
    ("closed_on", "days", "expected"),
    [
        (D(2026, 11, 2), 7, Occurrence("2026-11-09", D(2026, 11, 9), D(2026, 11, 10))),
        (D(2026, 11, 2), 1, Occurrence("2026-11-03", D(2026, 11, 3), D(2026, 11, 3))),
        (D(2026, 11, 2), 30, Occurrence("2026-12-02", D(2026, 12, 2), D(2026, 12, 6))),
        (D(2026, 12, 30), 365, Occurrence("2027-12-30", D(2027, 12, 30), D(2028, 1, 5))),
    ],
)
def test_interval_counts_from_the_day_it_was_done(closed_on: date, days: int, expected: Occurrence) -> None:
    assert interval_after(closed_on, days) == expected


@pytest.mark.parametrize(
    ("timing", "year", "expected"),
    [
        (yearly(3, 3), 2026, [3]),
        (yearly(11, 2), 2026, [1, 2, 11, 12]),
        (TaskTiming(recurrence="once", due_date=D(2026, 5, 9)), 2026, [5]),
        (TaskTiming(recurrence="once", due_date=D(2027, 5, 9)), 2026, []),
        (TaskTiming(recurrence="interval", interval_days=14, start_date=D(2026, 1, 1)), 2026, list(range(1, 13))),
        (TaskTiming(recurrence="interval", interval_days=120, start_date=D(2026, 2, 10)), 2026, [2, 6, 10]),
    ],
)
def test_months_in_year_for_the_calendar(timing: TaskTiming, year: int, expected: list[int]) -> None:
    assert months_in_year(timing, year) == expected
