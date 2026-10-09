"""Net Worth: the Asset Balances minus the Liability Balances."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Min

from apps.accounts.models import BALANCE_KINDS, Account, AccountKind, AccountQuerySet


@dataclass(frozen=True)
class NetWorth:
    """The Assets and Liabilities totals behind a Net Worth figure."""

    assets: Decimal
    liabilities: Decimal

    @property
    def total(self) -> Decimal:
        """Net Worth; a Liability's Balance is what is owed, so it subtracts."""
        return self.assets - self.liabilities


def _included() -> AccountQuerySet:
    return Account.objects.filter(kind__in=BALANCE_KINDS, include_in_net_worth=True)


def net_worth(as_of: date) -> NetWorth:
    """Net Worth as of a date: the sum of each Account's value, hidden ones included."""
    totals: dict[str, Decimal] = dict.fromkeys(BALANCE_KINDS, Decimal("0.00"))
    for account in _included().with_balance(as_of):
        totals[account.kind] += account.balance
    return NetWorth(
        assets=totals[AccountKind.ASSET], liabilities=totals[AccountKind.LIABILITY]
    )


def _month_end(when: date) -> date:
    next_month = (when.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def net_worth_history(today: date) -> list[tuple[date, Decimal]]:
    """Net Worth at each month-end from the earliest Opening Balance, then today.

    Every point uses today's include settings; one query per point.
    """
    start = _included().aggregate(start=Min("opening_balance_date"))["start"]
    if start is None:
        return []
    points = []
    when = _month_end(start)
    while when < today:
        points.append(when)
        when = _month_end(when + timedelta(days=1))
    points.append(today)
    return [(when, net_worth(when).total) for when in points]
