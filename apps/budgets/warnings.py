"""The digest's Budgets section: a Budget that has become close or gone over.

Each Budget, and the Overall Budget, is warned about at most once per level a
month. Only the digest email records a warning as sent, so viewing the
Upcoming panel never uses one up; both show it through the day it is sent.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.urls import reverse

from apps.accounts.forecast import Item
from apps.budgets.models import BudgetWarning
from apps.budgets.picture import State, budget_picture

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from apps.accounts.models import Account

LABELS = {State.CLOSE: "close to", State.OVER: "over"}


@dataclass(frozen=True)
class _Warning:
    account: Account | None
    level: State
    item: Item


def budget_warnings(today: date) -> list[Item]:
    """Each close or over Budget this month not warned about before today."""
    return [warning.item for warning in _unsent(today)]


def record_budget_warnings(today: date) -> None:
    """Mark today's warnings as sent, so later digests this month leave them out."""
    for warning in _unsent(today):
        BudgetWarning.objects.get_or_create(
            account=warning.account,
            month=today.replace(day=1),
            level=warning.level,
            defaults={"sent_on": today},
        )


def _unsent(today: date) -> list[_Warning]:
    """Close or over Budgets, leaving out those already sent this month.

    Once over has been sent, close is left out too: it would be old news.
    """
    month = today.replace(day=1)
    picture = budget_picture(month)
    states: list[tuple[Account | None, State, Decimal]] = [
        (row.account, row.state, row.spent) for row in picture.rows
    ]
    if picture.overall:
        states.append((None, picture.overall.state, picture.overall.spent))
    sent = set(
        BudgetWarning.objects.filter(month=month, sent_on__lt=today).values_list(
            "account_id", "level"
        )
    )
    url = reverse("budget_list")
    return [
        _Warning(account, state, Item(today, _label(account, state), spent, url))
        for account, state, spent in states
        if state in LABELS
        and not {(_pk(account), state), (_pk(account), State.OVER)} & sent
    ]


def _pk(account: Account | None) -> int | None:
    return account.pk if account else None


def _label(account: Account | None, state: State) -> str:
    if account is None:
        return f"Spent {LABELS[state]} the Overall Budget"
    return f"{account}: Spent {LABELS[state]} its Budget"
