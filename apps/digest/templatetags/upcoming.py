"""The Upcoming panel: the digest's items inside Velora."""

from typing import TYPE_CHECKING, Any

from django import template
from django.utils import timezone

from apps.digest.upcoming import upcoming

if TYPE_CHECKING:
    from django.template.context import Context

register = template.Library()


@register.inclusion_tag("digest/_upcoming_panel.html", takes_context=True)
def upcoming_panel(context: Context) -> dict[str, Any]:
    """Today's Upcoming sections, in the user's Number Format and Privacy Mode."""
    return {"user": context.get("user"), "sections": upcoming(timezone.localdate())}
