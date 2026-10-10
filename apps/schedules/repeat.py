"""When a Schedule falls due, from its repeat rule."""

import calendar
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from apps.schedules.models import Schedule


def months_after(start: date, months: int) -> date:
    """The same day `months` later, or the month's last day if it is shorter."""
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def nth_due_date(schedule: Schedule, n: int) -> date:
    """The n-th due date, counting the start date as the 0th."""
    steps = n * schedule.every
    match schedule.unit:
        case "day":
            return schedule.start_date + timedelta(days=steps)
        case "week":
            return schedule.start_date + timedelta(weeks=steps)
        case "month":
            return months_after(schedule.start_date, steps)
        case _:
            return months_after(schedule.start_date, 12 * steps)


def due_dates(schedule: Schedule, since: date, until: date) -> Iterator[date]:
    """The due dates from `since` to `until`, both included, before any end."""
    last = min(until, schedule.ends_on) if schedule.ends_on else until
    n = 0
    while (due := nth_due_date(schedule, n)) <= last:
        if due >= since:
            yield due
        n += 1
