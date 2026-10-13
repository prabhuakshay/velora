"""Prices and portfolio values over time, for charts."""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from apps.accounts.models import Account
from apps.accounts.net_worth import AccountRow, balances_on, month_ends
from apps.home.charts import Line, line
from apps.investments.valuation import Valuer

if TYPE_CHECKING:
    from datetime import date


def last_each_month[T](points: list[tuple[date, T]]) -> list[tuple[date, T]]:
    """The last of the date-ordered points in each month."""
    last: dict[tuple[int, int], tuple[date, T]] = {}
    for point in points:
        last[point[0].year, point[0].month] = point
    return list(last.values())


@dataclass(frozen=True)
class ValuePoint:
    """Every Investment Account's Market Value and Invested at the end of a day."""

    day: date
    market_value: Decimal
    invested: Decimal


def value_history(today: date) -> list[ValuePoint]:
    """The portfolio's value at each month-end since the first opened, and today.

    Market Value includes Cash, as the overview's totals do; Invested is the
    Cost Basis of the Holdings. A constant number of queries.
    """
    # Asset Accounts always have an Opening Balance date, by their check constraint.
    accounts = cast(
        "list[AccountRow]",
        list(
            Account.objects.investment().values_list(
                "pk", "kind", "opening_balance", "opening_balance_date"
            )
        ),
    )
    if not accounts:
        return []
    dates = month_ends(min(opened for *_, opened in accounts), today)
    opened_on = {pk: opened for pk, *_, opened in accounts}
    valuer = Valuer(list(opened_on), today)
    points = []
    for when, balances in balances_on(accounts, dates).items():
        market_value = invested = Decimal(0)
        for pk, balance in balances.items():
            value, cost = valuer.position(pk, opened_on[pk], balance, when)
            market_value += value
            invested += cost
        points.append(ValuePoint(when, market_value, invested))
    return points


@dataclass(frozen=True)
class ValueChart:
    """Market Value and Invested drawn on one scale."""

    market_value: Line
    invested: Line


def value_chart(points: list[ValuePoint]) -> ValueChart | None:
    """The two lines over the points; None with fewer than two to join."""
    if len(points) < 2:  # noqa: PLR2004
        return None
    values = [p.market_value for p in points] + [p.invested for p in points]
    low, high = min(values), max(values)
    return ValueChart(
        market_value=line([p.market_value for p in points], low, high),
        invested=line([p.invested for p in points], low, high),
    )
