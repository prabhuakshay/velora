"""The Upcoming panel: the digest's items inside Velora."""

from typing import TYPE_CHECKING, Any

from django import template
from django.utils import timezone

from apps.budgets.warnings import due_warnings
from apps.digest.upcoming import upcoming

if TYPE_CHECKING:
    from django.template.context import Context

    from apps.budgets.picture import BudgetPicture

register = template.Library()


@register.inclusion_tag("digest/_upcoming_panel.html", takes_context=True)
def upcoming_panel(
    context: Context, picture: BudgetPicture | None = None
) -> dict[str, Any]:
    """Today's Upcoming sections, in the user's Number Format and Privacy Mode.

    A page that already built this month's budget picture passes it in.
    """
    today = timezone.localdate()
    return {
        "user": context.get("user"),
        "sections": upcoming(today, due_warnings(today, picture)),
    }
