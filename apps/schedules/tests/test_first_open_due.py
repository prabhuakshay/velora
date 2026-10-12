from datetime import date

import pytest

from apps.schedules.models import Schedule
from apps.schedules.repeat import first_open_due


@pytest.mark.parametrize(
    ("start_date", "resumed_on", "last_due", "earliest", "expected"),
    [
        (date(2026, 10, 5), None, None, date(2026, 10, 1), date(2026, 10, 5)),
        (
            date(2026, 1, 5),
            date(2026, 10, 7),
            None,
            date(2026, 10, 1),
            date(2026, 10, 7),
        ),
        (
            date(2026, 1, 5),
            date(2026, 9, 1),
            None,
            date(2026, 10, 1),
            date(2026, 10, 1),
        ),
        (
            date(2026, 1, 5),
            date(2026, 9, 1),
            date(2026, 10, 5),
            date(2026, 10, 1),
            date(2026, 10, 6),
        ),
    ],
    ids=["start_date", "resumed_on", "earliest", "last_due"],
)
def test_the_latest_bound_wins(
    start_date: date,
    resumed_on: date | None,
    last_due: date | None,
    earliest: date,
    expected: date,
) -> None:
    schedule = Schedule(start_date=start_date, resumed_on=resumed_on)

    assert first_open_due(schedule, last_due, earliest) == expected
