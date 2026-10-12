"""What an Account did over time: month by month, and Transaction by Transaction."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth

from apps.core.dates import months_after
from apps.transactions.models import Split

if TYPE_CHECKING:
    from collections.abc import Sequence

    from apps.accounts.models import Account
    from apps.transactions.models import Transaction

MONTHS = 12
# The CSP blocks inline styles, so bar sizes go into SVG attributes, in
# viewBox units on a chart 100 tall.
HEIGHT = 100


@dataclass(frozen=True)
class Month:
    """One calendar month of an Account's Splits.

    net follows the kind's usual way, like with_activity(); balance is the
    month-end Balance of an Asset or Liability Account open by then.
    """

    start: date
    moved_in: Decimal
    moved_out: Decimal
    net: Decimal
    balance: Decimal | None


@dataclass(frozen=True)
class Bar:
    """One month's bar, in viewBox units, with the zero line at baseline."""

    start: date
    value: Decimal | None
    y: float
    height: float
    baseline: float
    negative: bool
    current: bool


@dataclass(frozen=True)
class Row:
    """A Transaction as the Account sees it.

    change is how far it moves the Balance for an Asset or Liability Account,
    so a payment off a Liability is negative, and the amount spent or earned
    for an Expense or Income one. balance_after is set for Asset and Liability
    Accounts only.
    """

    transaction: Transaction
    change: Decimal
    balance_after: Decimal | None


def month_end(start: date) -> date:
    """The last day of the month starting on start."""
    return months_after(start, 1) - timedelta(days=1)


def _touching(account: Account) -> Q:
    return Q(from_account=account) | Q(to_account=account)


def _moves(account: Account) -> dict[str, Sum]:
    return {
        "moved_in": Sum("amount", filter=Q(to_account=account), default=Decimal(0)),
        "moved_out": Sum("amount", filter=Q(from_account=account), default=Decimal(0)),
    }


def months(account: Account, today: date, count: int = MONTHS) -> list[Month]:
    """The last count months up to today's, oldest first."""
    first = months_after(today.replace(day=1), 1 - count)
    totals: dict[date, tuple[Decimal, Decimal]] = {
        month: (moved_in, moved_out)
        for month, moved_in, moved_out in Split.objects.filter(_touching(account))
        .annotate(month=TruncMonth("transaction__date"))
        .values("month")
        .annotate(**_moves(account))
        .values_list("month", "moved_in", "moved_out")
        .order_by("month")
    }
    running = account.opening_balance or Decimal(0)
    for month, (moved_in, moved_out) in totals.items():
        if month < first:
            running += account.sign * (moved_in - moved_out)
    result = []
    for offset in range(count):
        start = months_after(first, offset)
        moved_in, moved_out = totals.get(start, (Decimal(0), Decimal(0)))
        net = account.sign * (moved_in - moved_out)
        running += net
        opened = account.has_opening_balance and not account.opens_after(
            month_end(start)
        )
        result.append(
            Month(
                start=start,
                moved_in=moved_in,
                moved_out=moved_out,
                net=net,
                balance=running if opened else None,
            )
        )
    return result


def bars(
    starts: Sequence[date],
    values: Sequence[Decimal | None],
    *,
    owes: bool = False,
) -> list[Bar]:
    """Lay out one bar per month from each month's start and value, if any.

    For what is owed, below zero is in credit, so no bar is marked negative.
    """
    known = [value for value in values if value is not None]
    high = max([Decimal(0), *known])
    low = min([Decimal(0), *known])
    span = high - low
    baseline = float(high / span * HEIGHT) if span else float(HEIGHT)
    laid_out = []
    for index, (start, value) in enumerate(zip(starts, values, strict=True)):
        size = float(abs(value) / span * HEIGHT) if span and value else 0.0
        below = value is not None and value < 0
        laid_out.append(
            Bar(
                start=start,
                value=value,
                y=baseline if below else baseline - size,
                height=size,
                baseline=baseline,
                negative=below and not owes,
                current=index == len(starts) - 1,
            )
        )
    return laid_out


def rows(account: Account, transactions: Sequence[Transaction]) -> list[Row]:
    """Each Transaction with its change to the Account and the Balance just after.

    The Transactions come newest first, with only the Splits touching the
    Account prefetched.
    """
    if not transactions:
        return []
    newest = transactions[0]
    newer = Split.objects.filter(_touching(account)).filter(
        Q(transaction__date__gt=newest.date)
        | Q(transaction__date=newest.date, transaction__pk__gt=newest.pk)
    )
    totals = newer.aggregate(**_moves(account))
    balance: Decimal | None = getattr(account, "balance", None)
    if balance is not None:
        balance -= account.sign * (totals["moved_in"] - totals["moved_out"])
    result = []
    for transaction in transactions:
        moved_in = sum(
            (
                split.amount if split.to_account_id == account.pk else -split.amount
                for split in transaction.splits.all()
            ),
            Decimal(0),
        )
        change = account.sign * moved_in
        result.append(
            Row(transaction=transaction, change=change, balance_after=balance)
        )
        if balance is not None:
            balance -= change
    return result
