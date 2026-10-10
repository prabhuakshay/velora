"""What every page needs to show AI Quick Add and the Drafts count."""

from typing import TYPE_CHECKING, Any

from apps.quick_add import openrouter
from apps.quick_add.models import MAX_TEXT_LENGTH, Draft

if TYPE_CHECKING:
    from django.http import HttpRequest


def quick_add(request: HttpRequest) -> dict[str, Any]:  # noqa: ARG001
    """Whether AI Quick Add is on, the Quick Add box's limit and the Drafts count."""
    # A callable, so only pages that show the count run the query.
    context: dict[str, Any] = {"draft_count": Draft.objects.waiting().count}
    if not openrouter.is_configured():
        return context | {"quick_add_enabled": False}
    return context | {
        "quick_add_enabled": True,
        "quick_add_max_length": MAX_TEXT_LENGTH,
    }
