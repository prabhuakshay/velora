"""Net Worth: the Asset Balances minus the Liability Balances.

An Investment Account counts at its Market Value instead of its Balance.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import cast

from django.db.models import Min, Q, Sum
from django.db.models.functions import TruncMonth

from apps.accounts.models import BALANCE_KINDS, Account, AccountKind, AccountQuerySet
from apps.core.dates import month_start
from apps.investments.valuation import Valuer
from apps.transactions.models import Split


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
    accounts = list(_included().with_balance(as_of))
    valuer = Valuer([a.pk for a in accounts if a.is_investment], as_of)
    for account in accounts:
        value = account.balance
        if account.is_investment and not account.opens_after(as_of):
            value = valuer.market_value(
                account.pk, cast("date", account.opening_balance_date), value, as_of
            )
        totals[account.kind] += value
    return NetWorth(
        assets=totals[AccountKind.ASSET], liabilities=totals[AccountKind.LIABILITY]
    )


def _month_end(when: date) -> date:
    next_month = (when.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


type AccountRow = tuple[int, str, Decimal, date]


def balances_on(
    accounts: list[AccountRow], dates: list[date]
) -> dict[date, dict[int, Decimal]]:
    """Each account's Balance as of each date it is open on, in one query.

    Accounts are (pk, kind, opening balance, opening date). Splits are summed
    by month, so every date but the latest must be a month-end.
    """
    moved_in: dict[int, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    if accounts and dates:
        pks = [pk for pk, *_ in accounts]
        for source, destination, month, total in (
            Split.objects.filter(
                Q(from_account__in=pks) | Q(to_account__in=pks),
                transaction__date__lte=max(dates),
            )
            .annotate(month=TruncMonth("transaction__date"))
            .order_by()
            .values("from_account", "to_account", "month")
            .annotate(total=Sum("amount"))
            .values_list("from_account", "to_account", "month", "total")
        ):
            moved_in[source][month] -= total
            moved_in[destination][month] += total
    result: dict[date, dict[int, Decimal]] = {}
    for when in dates:
        result[when] = {}
        for pk, kind, opening, opened in accounts:
            if opened > when:
                continue
            moved = sum(
                (
                    total
                    for month, total in moved_in[pk].items()
                    if month <= month_start(when)
                ),
                Decimal(0),
            )
            result[when][pk] = (
                opening - moved if kind == AccountKind.LIABILITY else (opening + moved)
            )
    return result


def net_worth_on(dates: list[date]) -> dict[date, NetWorth]:
    """Net Worth as of each date, in two queries whatever the number of dates.

    Every date but the latest must be a month-end.
    """
    # Asset and Liability Accounts always have both, by their check constraint.
    accounts = cast(
        "list[tuple[int, str, Decimal, date, str]]",
        list(
            _included().values_list(
                "pk",
                "kind",
                "opening_balance",
                "opening_balance_date",
                "investment_mode",
            )
        ),
    )
    investments = {pk: opened for pk, _, _, opened, mode in accounts if mode}
    kinds = {pk: kind for pk, kind, *_ in accounts}
    valuer = Valuer(list(investments), max(dates, default=date.min))
    balances = balances_on([row[:4] for row in accounts], dates)
    result = {}
    for when in dates:
        totals: dict[str, Decimal] = dict.fromkeys(BALANCE_KINDS, Decimal("0.00"))
        for pk, balance in balances[when].items():
            value = balance
            if pk in investments:
                value = valuer.market_value(pk, investments[pk], balance, when)
            totals[kinds[pk]] += value
        result[when] = NetWorth(
            assets=totals[AccountKind.ASSET],
            liabilities=totals[AccountKind.LIABILITY],
        )
    return result


def month_ends(start: date, today: date) -> list[date]:
    """Each month-end from start's month until before today, then today."""
    points = []
    when = _month_end(start)
    while when < today:
        points.append(when)
        when = _month_end(when + timedelta(days=1))
    points.append(today)
    return points


def history_dates(today: date, since: date | None = None) -> list[date]:
    """Each month-end from the earliest Opening Balance, then today.

    With since, month-ends before it are left out; none without an included
    Asset or Liability Account.
    """
    start = _included().aggregate(start=Min("opening_balance_date"))["start"]
    if start is None:
        return []
    if since is not None:
        start = max(start, since)
    return month_ends(start, today)


def net_worth_history(
    today: date, since: date | None = None
) -> list[tuple[date, Decimal]]:
    """Net Worth at each of history_dates, using today's include settings."""
    points = history_dates(today, since)
    values = net_worth_on(points)
    return [(when, values[when].total) for when in points]
