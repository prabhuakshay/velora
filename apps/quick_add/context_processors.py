"""What every page needs to show or hide AI Quick Add."""

from typing import TYPE_CHECKING, Any

from apps.quick_add import openrouter
from apps.quick_add.models import MAX_TEXT_LENGTH, QuickAdd

if TYPE_CHECKING:
    from django.http import HttpRequest


def quick_add(request: HttpRequest) -> dict[str, Any]:  # noqa: ARG001
    """Whether AI Quick Add is on, the Quick Add box's limit and the Drafts count."""
    if not openrouter.is_configured():
        return {"quick_add_enabled": False}
    return {
        "quick_add_enabled": True,
        "quick_add_max_length": MAX_TEXT_LENGTH,
        # A callable, so only pages that show the count run the query.
        "draft_count": QuickAdd.objects.filter(status=QuickAdd.Status.DRAFT).count,
    }
