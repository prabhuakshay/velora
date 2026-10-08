from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from apps.budget.models import Category, CategoryGroup

if TYPE_CHECKING:
    from datetime import datetime

PAGE_SIZE = 5

# Fields whose change reads "Changed <label> of <name>".
CHANGED_LABELS = {
    "icon": "icon",
    "kind": "kind",
    "description": "description",
    "color": "colour",
}


@dataclass
class Entry:
    text: str
    when: datetime


def _group_name(group_id: int) -> str:
    record = CategoryGroup.history.filter(id=group_id).order_by("-history_id").first()
    return record.name if record else ""


def _describe_change(change: Any, name: str) -> str:  # noqa: ANN401
    if change.field == "name":
        return f"Renamed {change.old} → {change.new}"
    if change.field == "group":
        return f"Moved {name} to {_group_name(change.new)}"
    if change.field == "hidden":
        return f"{'Hidden' if change.new else 'Unhidden'} {name}"
    return f"Changed {CHANGED_LABELS[change.field]} of {name}"


def _describe(record: Any) -> str:  # noqa: ANN401
    name = record.name
    if record.history_type == "+":
        return f"Created {name}"
    if record.history_type == "-":
        return f"Deleted {name}"
    changes = record.diff_against(record.prev_record).changes
    parts = [
        _describe_change(c, name)
        for c in changes
        if c.field in CHANGED_LABELS or c.field in {"name", "group", "hidden"}
    ]
    return "; ".join(parts) or f"Updated {name}"


def recent_entries(owner_id: int, offset: int) -> tuple[list[Entry], bool]:
    """Return one page of the owner's history, newest first, and whether more follow."""
    groups = CategoryGroup.history.filter(owner_id=owner_id)
    categories = Category.history.filter(group_id__in=groups.values("id"))
    # Fetching one row past the page tells us whether another page exists.
    limit = offset + PAGE_SIZE + 1
    newest_first = ("-history_date", "-history_id")
    records = [*groups.order_by(*newest_first)[:limit]]
    records += [*categories.order_by(*newest_first)[:limit]]
    records.sort(key=lambda r: (r.history_date, r.history_id), reverse=True)
    page = records[offset : offset + PAGE_SIZE]
    has_more = len(records) > offset + PAGE_SIZE
    return [Entry(_describe(r), r.history_date) for r in page], has_more
