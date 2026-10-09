"""Background jobs that turn Quick Adds into Drafts (ADR 0005)."""

from procrastinate.contrib.django import app

from apps.quick_add import drafting
from apps.quick_add.models import QuickAdd


@app.task(name="quick_add.process_quick_add")
def process_quick_add(quick_add_id: int) -> None:
    """Ask the AI for a Draft of the Quick Add."""
    drafting.draft_quick_add(QuickAdd.objects.get(pk=quick_add_id))
