"""Readable activity feed built from category and expense account history."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from apps.budget.models import Category, ExpenseAccount

if TYPE_CHECKING:
    from datetime import datetime

    from django.db import models

PAGE_SIZE = 5

# Each tracked model's kind, and its fields whose change reads
# "Changed <label> of <name>".
SOURCES: dict[str, tuple[type[models.Model], dict[str, str]]] = {
    "category": (
        Category,
        {
            "icon": "icon",
            "kind": "kind",
            "description": "description",
            "color": "colour",
        },
    ),
    "expense_account": (ExpenseAccount, {"notes": "notes"}),
}


@dataclass
class Entry:
    """One line of the activity feed."""

    text: str
    when: datetime
    kind: str


def _previous_versions(model: type[models.Model], page: list[Any]) -> dict[int, Any]:
    """Map each record to the version before it, in one query per model."""
    previous: dict[int, Any] = {}
    wanted = {r.history_id for r in page}
    last: dict[int, Any] = {}
    versions = model.history.filter(id__in={r.id for r in page}).order_by(  # type: ignore[attr-defined]
        "history_date", "history_id"
    )
    for version in versions:
        if version.history_id in wanted:
            previous[version.history_id] = last.get(version.id)
        last[version.id] = version
    return previous


def _describe_change(change: Any, name: str, labels: dict[str, str]) -> str:  # noqa: ANN401
    if change.field == "name":
        return f"Renamed {change.old} → {change.new}"
    if change.field == "hidden":
        return f"{'Hidden' if change.new else 'Unhidden'} {name}"
    return f"Changed {labels[change.field]} of {name}"


def _describe(record: Any, previous: Any, labels: dict[str, str]) -> str:  # noqa: ANN401
    name = record.name
    if record.history_type == "+":
        return f"Created {name}"
    if record.history_type == "-":
        # A Merge stores the target's name as the deletion's change reason.
        if record.history_change_reason:
            return f"Merged {name} into {record.history_change_reason}"
        return f"Deleted {name}"
    changes = record.diff_against(previous).changes
    parts = [
        _describe_change(c, name, labels)
        for c in changes
        if c.field in labels or c.field in {"name", "hidden"}
    ]
    return "; ".join(parts) or f"Updated {name}"


def recent_entries(offset: int) -> tuple[list[Entry], bool]:
    """Return one page of history, newest first, and whether more follow."""
    # Fetching one row past the page tells us whether another page exists.
    limit = offset + PAGE_SIZE + 1
    records = [
        (kind, record)
        for kind, (model, _) in SOURCES.items()
        for record in model.history.order_by("-history_date", "-history_id")[:limit]  # type: ignore[attr-defined]
    ]
    records.sort(
        key=lambda kr: (kr[1].history_date, kr[0], kr[1].history_id), reverse=True
    )
    page = records[offset : offset + PAGE_SIZE]
    has_more = len(records) > offset + PAGE_SIZE

    previous = {
        kind: _previous_versions(model, [r for k, r in page if k == kind])
        for kind, (model, _) in SOURCES.items()
    }
    entries = [
        Entry(
            _describe(r, previous[kind].get(r.history_id), SOURCES[kind][1]),
            r.history_date,
            kind,
        )
        for kind, r in page
    ]
    return entries, has_more
