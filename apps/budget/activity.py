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


class _Context:
    """History lookups for one page, fetched up front to avoid per-entry queries."""

    def __init__(self, owner_id: int, page: list[Any]) -> None:
        self.group_history = [
            *CategoryGroup.history.filter(owner_id=owner_id).order_by(
                "history_date", "history_id"
            )
        ]
        self.previous: dict[tuple[type, int], Any] = {}
        for model in (CategoryGroup, Category):
            wanted = {r.history_id for r in page if r.instance_type is model}
            ids = {r.id for r in page if r.instance_type is model}
            last: dict[int, Any] = {}
            versions = model.history.filter(id__in=ids).order_by(
                "history_date", "history_id"
            )
            for version in versions:
                if version.history_id in wanted:
                    self.previous[model, version.history_id] = last.get(version.id)
                last[version.id] = version

    def group_name(self, group_id: int, at: datetime) -> str:
        names = [
            g.name
            for g in self.group_history
            if g.id == group_id and g.history_date <= at
        ]
        return names[-1] if names else "another group"


def _describe_change(change: Any, record: Any, ctx: _Context) -> str:  # noqa: ANN401
    name = record.name
    if change.field == "name":
        return f"Renamed {change.old} → {change.new}"
    if change.field == "group":
        return f"Moved {name} to {ctx.group_name(change.new, record.history_date)}"
    if change.field == "hidden":
        return f"{'Hidden' if change.new else 'Unhidden'} {name}"
    return f"Changed {CHANGED_LABELS[change.field]} of {name}"


def _describe(record: Any, ctx: _Context) -> str:  # noqa: ANN401
    name = record.name
    if record.history_type == "+":
        return f"Created {name}"
    if record.history_type == "-":
        return f"Deleted {name}"
    previous = ctx.previous.get((record.instance_type, record.history_id))
    changes = record.diff_against(previous).changes
    parts = [
        _describe_change(c, record, ctx)
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
    ctx = _Context(owner_id, page)
    return [Entry(_describe(r, ctx), r.history_date) for r in page], has_more
