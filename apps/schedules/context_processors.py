"""What every page needs to show the Suggested Schedules waiting count."""

from typing import TYPE_CHECKING, Any

from apps.schedules.models import SuggestedSchedule

if TYPE_CHECKING:
    from django.http import HttpRequest


def suggested_schedules(request: HttpRequest) -> dict[str, Any]:  # noqa: ARG001
    """How many Suggested Schedules wait for the user."""
    waiting = SuggestedSchedule.objects.filter(status=SuggestedSchedule.Status.WAITING)
    # A callable, so only pages that show the count run the query.
    return {"suggested_schedule_count": waiting.count}
