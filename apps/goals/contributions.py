"""What a Goal's linked Schedules add to it each month, and for how long."""

import itertools
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.core.dates import months_after
from apps.goals.projection import Contribution
from apps.schedules.estimates import last_paid_amount
from apps.schedules.repeat import all_due_dates, due_dates

if TYPE_CHECKING:
    from apps.schedules.models import Schedule

NOTHING = Contribution(monthly=Decimal(0), months=0)


def _each_time(schedule: Schedule, today: date) -> Decimal:
    """Its amount, with open amounts estimated the way the Forecast does."""
    total = Decimal(0)
    for split in schedule.splits.all():
        amount = split.amount
        if amount is None:
            amount = last_paid_amount(split, today)
        total += amount or 0
    return total


def _times_a_year(schedule: Schedule, today: date) -> int:
    since = max(today, schedule.start_date)
    year_end = months_after(since, 12) - timedelta(days=1)
    # Ignoring any end: when it stops is how long it pays, not how often.
    upcoming = itertools.dropwhile(lambda due: due < since, all_due_dates(schedule))
    return sum(1 for _ in itertools.takewhile(lambda due: due <= year_end, upcoming))


def contribution(schedule: Schedule, today: date, until: date) -> Contribution:
    """Its monthly-equivalent amount, paid until its end or `until`."""
    yearly = _times_a_year(schedule, today)
    if not schedule.active or not yearly:
        return NOTHING
    remaining = sum(1 for _ in due_dates(schedule, today, until))
    return Contribution(
        monthly=_each_time(schedule, today) * yearly / 12,
        months=round(remaining * 12 / yearly),
    )
