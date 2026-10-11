"""Due dates and Schedule states as the Schedules pages show them."""

from typing import TYPE_CHECKING

from django import template

if TYPE_CHECKING:
    from datetime import date

    from apps.schedules.models import Schedule

register = template.Library()


@register.filter
def days_away(day: date, today: date) -> str:
    """Today, tomorrow, yesterday, in 3 days or 3 days ago."""
    days = (day - today).days
    match days:
        case 0:
            return "today"
        case 1:
            return "tomorrow"
        case -1:
            return "yesterday"
    return f"in {days} days" if days > 0 else f"{-days} days ago"


@register.filter
def has_ended(schedule: Schedule, today: date) -> bool:
    """Whether the Schedule was ended before today."""
    return schedule.has_ended(today)
