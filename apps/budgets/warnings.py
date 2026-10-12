"""The digest's Budgets section: a Budget that has become close or gone over.

Each Budget, and the Overall Budget, is warned about at most once per level a
month. Only the digest email records a warning as sent, so viewing the
Upcoming panel never uses one up; both show it through the day it is sent.
"""

from typing import TYPE_CHECKING

from django.urls import reverse

from apps.accounts.forecast import Item
from apps.budgets.models import BudgetWarning
from apps.budgets.picture import Row, State, budget_picture
from apps.core.dates import month_start

if TYPE_CHECKING:
    from datetime import date

LABELS = {State.CLOSE: "close to", State.OVER: "over"}


def due_warnings(today: date) -> list[Row]:
    """Close or over Budgets this month not warned about before today.

    Once over has been sent, close is left out too: it would be old news.
    """
    month = month_start(today)
    picture = budget_picture(month)
    rows: list[Row] = [*picture.rows]
    if picture.overall:
        rows.append(picture.overall)
    sent = {
        (warning.account, warning.level)
        for warning in BudgetWarning.objects.filter(
            month=month, sent_on__lt=today
        ).select_related("account")
    }
    return [
        row
        for row in rows
        if row.state in LABELS
        and not {(row.account, row.state), (row.account, State.OVER)} & sent
    ]


def warning_items(rows: list[Row], today: date) -> list[Item]:
    """The warnings as Items dated today, linking to the Budgets page."""
    url = reverse("budget_list")
    return [Item(today, _label(row), row.spent, url) for row in rows]


def record_budget_warnings(rows: list[Row], today: date) -> None:
    """Mark the warnings as sent, so later digests this month leave them out."""
    for row in rows:
        BudgetWarning.objects.get_or_create(
            account=row.account,
            month=month_start(today),
            level=row.state,
            defaults={"sent_on": today},
        )


def _label(row: Row) -> str:
    if row.account is None:
        return f"Spent {LABELS[row.state]} the Overall Budget"
    return f"{row.account}: Spent {LABELS[row.state]} its Budget"
