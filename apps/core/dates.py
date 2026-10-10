"""Calendar arithmetic that clamps to the end of shorter months."""

import calendar
from datetime import date


def day_of(year: int, month: int, day: int) -> date:
    """That day of the month, or its last day if the month is shorter.

    The month may run past 12 or below 1; it rolls into the next or last year.
    """
    month_index = month - 1
    year, month = year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def months_after(start: date, months: int) -> date:
    """The same day `months` later, or the month's last day if it is shorter."""
    return day_of(start.year, start.month + months, start.day)
