"""What the Forecast page shows: one scope's Balances, chart and timeline."""

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import groupby
from typing import TYPE_CHECKING

from django.urls import reverse

from apps.accounts.models import Account, AccountKind

if TYPE_CHECKING:
    from datetime import date

    from apps.accounts.forecast import Forecast, Item, Move

HORIZONS = (7, 30, 60, 90)
CHART_WIDTH = 600
CHART_HEIGHT = 160


@dataclass(frozen=True)
class Scope:
    """The Balances the page follows: one Account, or all Assets together."""

    now: Decimal
    balances: list[Decimal]
    account: Account | None = None
    account_ids: frozenset[int] = frozenset()

    @property
    def owes(self) -> bool:
        """Whether the Balance is what is owed, so going up is bad."""
        return self.account is not None and self.account.owes

    @property
    def threshold(self) -> Decimal | None:
        """The one Account's Low-Balance Threshold, when it warns at all."""
        if self.account is None or (
            self.owes and not self.account.low_balance_threshold
        ):
            return None
        return self.account.low_balance_threshold

    def change(self, move: Move) -> Decimal:
        """How far the move takes the Balance; 0 for one within the scope."""
        moved = Decimal(0)
        if move.to_account_id in self.account_ids:
            moved += move.amount
        if move.from_account_id in self.account_ids:
            moved -= move.amount
        return -moved if self.owes else moved


def scope_for(result: Forecast, account_pk: int | None) -> Scope:
    """The chosen Account's row, else every Asset's Balances added up."""
    for row in result.accounts:
        if row.account.pk == account_pk:
            return Scope(
                row.account.balance,
                row.balances,
                row.account,
                frozenset([row.account.pk]),
            )
    assets = [row for row in result.accounts if row.account.kind == AccountKind.ASSET]
    totals = [
        sum(day, Decimal(0)) for day in zip(*(r.balances for r in assets), strict=True)
    ]
    return Scope(
        sum((row.account.balance for row in assets), Decimal(0)),
        totals or [Decimal(0)] * len(result.days),
        account_ids=frozenset(row.account.pk for row in assets),
    )


@dataclass
class Entry:
    """One thing expected on a day; a Schedule or Draft's Splits make one Entry."""

    when: date
    label: str
    url: str
    source: str
    change: Decimal | None
    estimated: bool = False
    accounts: list[str] = field(default_factory=list)
    overdue_since: date | None = None


@dataclass(frozen=True)
class Day:
    """The Entries landing on a day and the Balance at its end."""

    day: date
    balance: Decimal
    entries: list[Entry]
    ahead: int


def _flow(move: Move, names: dict[int, Account]) -> str:
    ends = (move.from_account_id, move.to_account_id)
    return " → ".join(str(names[pk]) for pk in ends if pk in names)


def _entries(scope: Scope, result: Forecast, names: dict[int, Account]) -> list[Entry]:
    """The moves that reach the scope, merged by Schedule or Draft and date."""
    entries: dict[tuple[date, str], Entry] = {}
    for move in result.moves:
        if not {move.from_account_id, move.to_account_id} & scope.account_ids:
            continue
        key = (move.when, move.url)
        entry = entries.setdefault(
            key, Entry(move.when, move.label, move.url, move.source, Decimal(0))
        )
        entry.change = (entry.change or Decimal(0)) + scope.change(move)
        entry.estimated |= move.estimated
        entry.accounts.append(_flow(move, names))
    return list(entries.values())


def _unknown(scope: Scope, items: list[Item]) -> list[Entry]:
    return [
        Entry(item.when, item.label, item.url, "", None)
        for item in items
        if item.account_ids & scope.account_ids
    ]


def timeline(scope: Scope, result: Forecast) -> list[Day]:
    """Each day with something expected, oldest first, and its closing Balance.

    Anything overdue lands on the first day, as the Forecast counts it there.
    """
    ids = {
        pk for move in result.moves for pk in (move.from_account_id, move.to_account_id)
    }
    names = Account.objects.in_bulk(ids - {None})
    start = result.days[0]
    entries = _entries(scope, result, names) + _unknown(scope, result.amountless)
    for entry in entries:
        if entry.when < start:
            entry.overdue_since = entry.when
            entry.when = start
    entries.sort(key=lambda entry: (entry.when, entry.change is None, entry.label))
    balance_on = dict(zip(result.days, scope.balances, strict=True))
    return [
        Day(day, balance_on[day], list(group), (day - start).days)
        for day, group in groupby(entries, key=lambda entry: entry.when)
    ]


def totals(days: list[Day]) -> dict[str, Decimal]:
    """How far the expected moves raise and lower the Balance, in all."""
    changes = [entry.change for day in days for entry in day.entries if entry.change]
    return {
        "up": sum((c for c in changes if c > 0), Decimal(0)),
        "down": -sum((c for c in changes if c < 0), Decimal(0)),
    }


def worst(scope: Scope, result: Forecast) -> tuple[date, Decimal]:
    """The day with the lowest Balance, or the most owed; the earliest on a tie."""
    pairs = zip(result.days, scope.balances, strict=True)
    if scope.owes:
        return max(pairs, key=lambda pair: (pair[1], -pair[0].toordinal()))
    return min(pairs, key=lambda pair: (pair[1], pair[0]))


def chart(scope: Scope, result: Forecast, days: list[Day]) -> dict[str, object]:
    """SVG coordinates for the Balance line, the zero line and the threshold.

    Scaled to the Balances rather than from 0, so small moves stay visible.
    """
    values = scope.balances
    threshold = scope.threshold
    bounds: list[Decimal] = list(values)
    if threshold is not None:
        bounds.append(threshold)
    low, high = min(bounds), max(bounds)
    step = CHART_WIDTH / max(len(values) - 1, 1)
    busy = {day.day for day in days}

    def y(value: Decimal) -> float:
        if high == low:
            return CHART_HEIGHT / 2
        return float(CHART_HEIGHT - (value - low) / (high - low) * CHART_HEIGHT)

    points = " ".join(f"{step * i:.1f},{y(v):.1f}" for i, v in enumerate(values))
    return {
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
        "points": points,
        "area": f"0,{y(low):.1f} {points} {CHART_WIDTH},{y(low):.1f}",
        "zero": y(Decimal(0)) if low < 0 < high else None,
        "threshold": y(threshold) if threshold else None,
        "columns": [
            {"day": day, "balance": value, "busy": day in busy}
            for day, value in zip(result.days, values, strict=True)
        ],
    }


def account_rows(
    result: Forecast, selected: Account | None, length: int
) -> list[dict[str, object]]:
    """Each Account's Balance now and at the end, for switching the scope."""
    breached = {breach.account.pk: breach for breach in result.breaches}
    return [
        {
            "account": row.account,
            "now": row.account.balance,
            "end": row.balances[-1],
            "breach": breached.get(row.account.pk),
            "selected": row.account == selected,
            "url": _url(length, row.account.pk),
        }
        for row in result.accounts
    ]


def _url(length: int, account_pk: int | None = None) -> str:
    query = f"?days={length}" + (f"&account={account_pk}" if account_pk else "")
    return reverse("forecast") + query


def horizon_tabs(length: int, account: Account | None) -> list[dict[str, object]]:
    """Links to the same scope over each horizon."""
    return [
        {
            "days": days,
            "url": _url(days, account.pk if account else None),
            "active": days == length,
        }
        for days in HORIZONS
    ]
