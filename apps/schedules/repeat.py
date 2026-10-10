"""When a Schedule falls due, from its repeat rule."""

import itertools
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from croniter import CroniterBadDateError, croniter

from apps.core.dates import months_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from apps.schedules.models import Schedule


def nth_due_date(schedule: Schedule, n: int) -> date:
    """The n-th interval due date, counting the start date as the 0th."""
    steps = n * (schedule.every or 1)
    match schedule.unit:
        case "day":
            return schedule.start_date + timedelta(days=steps)
        case "week":
            return schedule.start_date + timedelta(weeks=steps)
        case "month":
            return months_after(schedule.start_date, steps)
        case _:
            return months_after(schedule.start_date, 12 * steps)


def cron_dates(expression: str, start: date) -> Iterator[date]:
    """Each day from `start` on with a time the cron expression matches."""
    # Just before midnight of the day before, so `start` itself can match.
    cursor = datetime.combine(start, time.min) - timedelta(microseconds=1)
    while True:
        try:
            day = croniter(expression, cursor).get_next(datetime).date()
        except CroniterBadDateError:
            return
        yield day
        cursor = datetime.combine(day, time.max)


def all_due_dates(schedule: Schedule) -> Iterator[date]:
    """Every due date of the rule from the start date, ignoring any end."""
    if schedule.cron:
        return cron_dates(schedule.cron, schedule.start_date)
    return (nth_due_date(schedule, n) for n in itertools.count())


def due_dates(schedule: Schedule, since: date, until: date) -> Iterator[date]:
    """The due dates from `since` to `until`, both included, before any end."""
    last = min(until, schedule.ends_on) if schedule.ends_on else until
    for due in itertools.islice(all_due_dates(schedule), schedule.ends_after):
        if due > last:
            return
        if due >= since:
            yield due
