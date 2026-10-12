"""The month's budget picture: each Budget against what was Spent and Expected.

Every page, card and digest reads its Budget numbers from budget_picture, so
nothing else recomputes them.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from django.db.models.functions import Lower
from django.urls import reverse

from apps.accounts.activity import month_end
from apps.accounts.expected import expected_spending
from apps.accounts.models import Account, AccountKind
from apps.budgets.models import Budget

if TYPE_CHECKING:
    from datetime import date


CLOSE_SHARE = Decimal("0.9")


class State(StrEnum):
    """How Spent stands against a Budget; Expected never moves it."""

    FINE = "fine"
    CLOSE = "close"
    OVER = "over"


def state_of(budget: Decimal, spent: Decimal) -> State:
    """Over past the Budget, close from 90% of it; a ₹0 Budget is never close."""
    if spent > budget:
        return State.OVER
    if spent > 0 and spent >= budget * CLOSE_SHARE:
        return State.CLOSE
    return State.FINE


@dataclass(frozen=True)
class Row:
    """A Budget for the month against what was Spent.

    With no Account it is the Overall Budget, against all Spent, Unbudgeted
    included.
    """

    account: Account | None
    budget: Decimal
    spent: Decimal

    @property
    def left(self) -> Decimal:
        """What can still be spent; negative once over."""
        return self.budget - self.spent

    @property
    def state(self) -> State:
        """Whether Spent is fine, close to or over the Budget."""
        return state_of(self.budget, self.spent)


@dataclass(frozen=True)
class BudgetRow(Row):
    """One Expense Account's Budget for the month, its Spent and its Expected."""

    account: Account
    expected: Decimal
    transactions_url: str


@dataclass(frozen=True)
class BudgetPicture:
    """A calendar month's Budgets."""

    month: date
    rows: list[BudgetRow]
    # Across every Expense Account, Unbudgeted ones included.
    total_expected: Decimal
    overall: Row | None
    unbudgeted: Decimal
    # Allowed so editing is never blocked, but worth a note on the page.
    budgets_add_up_to_more: bool


def budgets_in(month: date) -> dict[int, Decimal]:
    """Each Expense Account's Budget that applies in the month, by Account id."""
    newest = (
        Budget.objects.filter(account__isnull=False, month__lte=month)
        .order_by("account_id", "-month")
        .distinct("account_id")
        .values_list("account_id", "amount")
    )
    return {pk: amount for pk, amount in newest if amount is not None}


def overall_budget_in(month: date) -> Decimal | None:
    """The Overall Budget that applies in the month, if any."""
    newest = (
        Budget.objects.filter(account=None, month__lte=month).order_by("-month").first()
    )
    return newest.amount if newest else None


def budget_picture(month: date) -> BudgetPicture:
    """The Budgets of the month starting on the given first day."""
    budgets = budgets_in(month)
    end = month_end(month)
    expected = expected_spending(month, end)
    accounts = (
        Account.objects.filter(kind=AccountKind.EXPENSE)
        .with_activity("spent", month, end)
        .order_by(Lower("name"))
    )
    transactions = reverse("transaction_list")
    rows = [
        BudgetRow(
            account,
            budgets[account.pk],
            account.spent,
            expected.get(account.pk, Decimal(0)),
            f"{transactions}?"
            + urlencode({"account": account.pk, "start": month, "end": end}),
        )
        for account in accounts
        if account.pk in budgets
    ]
    unbudgeted = sum(
        (account.spent for account in accounts if account.pk not in budgets),
        Decimal(0),
    )
    overall = overall_budget_in(month)
    return BudgetPicture(
        month=month,
        rows=rows,
        total_expected=sum(expected.values(), Decimal(0)),
        overall=None
        if overall is None
        else Row(None, overall, sum((row.spent for row in rows), unbudgeted)),
        unbudgeted=unbudgeted,
        budgets_add_up_to_more=overall is not None and sum(budgets.values()) > overall,
    )
