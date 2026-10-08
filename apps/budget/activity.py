from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from apps.budget.models import Category

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


class _Context:
    """History lookups for one page, fetched up front to avoid per-entry queries."""

    def __init__(self, page: list[Any]) -> None:
        self.previous: dict[int, Any] = {}
        wanted = {r.history_id for r in page}
        last: dict[int, Any] = {}
        versions = Category.history.filter(id__in={r.id for r in page}).order_by(
            "history_date", "history_id"
        )
        for version in versions:
            if version.history_id in wanted:
                self.previous[version.history_id] = last.get(version.id)
            last[version.id] = version


def _describe_change(change: Any, record: Any) -> str:  # noqa: ANN401
    name = record.name
    if change.field == "name":
        return f"Renamed {change.old} → {change.new}"
    if change.field == "hidden":
        return f"{'Hidden' if change.new else 'Unhidden'} {name}"
    return f"Changed {CHANGED_LABELS[change.field]} of {name}"


def _describe(record: Any, ctx: _Context) -> str:  # noqa: ANN401
    name = record.name
    if record.history_type == "+":
        return f"Created {name}"
    if record.history_type == "-":
        return f"Deleted {name}"
    previous = ctx.previous.get(record.history_id)
    changes = record.diff_against(previous).changes
    parts = [
        _describe_change(c, record)
        for c in changes
        if c.field in CHANGED_LABELS or c.field in {"name", "hidden"}
    ]
    return "; ".join(parts) or f"Updated {name}"


def recent_entries(owner_id: int, offset: int) -> tuple[list[Entry], bool]:
    """Return one page of the owner's history, newest first, and whether more follow."""
    # Fetching one row past the page tells us whether another page exists.
    limit = offset + PAGE_SIZE + 1
    records = [
        *Category.history.filter(owner_id=owner_id).order_by(
            "-history_date", "-history_id"
        )[:limit]
    ]
    page = records[offset : offset + PAGE_SIZE]
    has_more = len(records) > offset + PAGE_SIZE
    ctx = _Context(page)
    return [Entry(_describe(r, ctx), r.history_date) for r in page], has_more
