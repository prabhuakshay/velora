"""What Investment Accounts are worth, from their Investment Events and Prices."""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.utils import timezone

from apps.investments.models import InvestmentEvent, Price
from apps.investments.replay import Book, cash, holding_value, market_value, replay

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import date

    from apps.accounts.models import Account
    from apps.investments.models import Instrument


def latest_prices(instruments: Collection[int]) -> dict[int, Price]:
    """Each Instrument's newest Price, in one query."""
    return {
        price.instrument_id: price
        for price in Price.objects.filter(instrument__in=instruments)
        .order_by("instrument_id", "-date")
        .distinct("instrument_id")
    }


@dataclass(frozen=True)
class HoldingRow:
    """One Instrument's line on an Investment Account's Holdings."""

    instrument: Instrument
    units: Decimal
    cost_basis: Decimal
    market_value: Decimal
    realized: Decimal
    price: Price | None
    stale: bool

    @property
    def unrealized(self) -> Decimal:
        """Market Value less Cost Basis."""
        return self.market_value - self.cost_basis


@dataclass(frozen=True)
class AccountValue:
    """An Investment Account's Cash, Holdings and Market Value now."""

    cash: Decimal
    market_value: Decimal
    holdings: list[HoldingRow]

    @property
    def cost_basis(self) -> Decimal:
        """The Cost Basis of every Holding together."""
        return sum((row.cost_basis for row in self.holdings), Decimal(0))

    @property
    def realized(self) -> Decimal:
        """The Realized Gain of every Sell, whatever its date."""
        return sum((row.realized for row in self.holdings), Decimal(0))

    @property
    def unrealized(self) -> Decimal:
        """Market Value of the Holdings less their Cost Basis."""
        return sum((row.unrealized for row in self.holdings), Decimal(0))


def account_value(account: Account, balance: Decimal) -> AccountValue:
    """Value the Investment Account at its latest Prices, given its Balance now."""
    events = list(account.investment_events.select_related("instrument"))
    book = replay(events)
    instruments = {event.instrument_id: event.instrument for event in events}
    prices = latest_prices(book.holdings)
    today = timezone.localdate()
    rows = [
        HoldingRow(
            instrument=instruments[pk],
            units=holding.units,
            cost_basis=holding.cost_basis,
            market_value=holding_value(holding, _value(prices.get(pk))),
            realized=holding.realized,
            price=prices.get(pk),
            stale=pk in prices and prices[pk].is_stale(today),
        )
        for pk, holding in book.holdings.items()
    ]
    rows.sort(key=lambda row: row.instrument.name)
    held = cash(balance, book, _opened(account))
    return AccountValue(
        cash=held,
        market_value=market_value(held, book, _values(prices)),
        holdings=rows,
    )


def _opened(account: Account) -> date:
    # Asset Accounts always have one, by their check constraint.
    return cast("date", account.opening_balance_date)


def _value(price: Price | None) -> Decimal | None:
    return None if price is None else price.price


def _values(prices: dict[int, Price]) -> dict[int, Decimal]:
    return {pk: price.price for pk, price in prices.items()}


class Valuer:
    """Values Investment Accounts on any dates up to until, in two queries.

    Each date uses the Investment Events up to it and the latest Price on or
    before it. Given no accounts, it makes no query at all.
    """

    def __init__(self, accounts: Collection[int], until: date) -> None:
        """Load the accounts' Investment Events and Prices up to until."""
        self.events: dict[int, list[InvestmentEvent]] = defaultdict(list)
        self.prices: dict[int, tuple[list[date], list[Decimal]]] = defaultdict(
            lambda: ([], [])
        )
        if not accounts:
            return
        for event in InvestmentEvent.objects.filter(
            account__in=accounts, date__lte=until
        ):
            self.events[event.account_id].append(event)
        instruments = {e.instrument_id for es in self.events.values() for e in es}
        for instrument, day, price in (
            Price.objects.filter(instrument__in=instruments, date__lte=until)
            .order_by("date")
            .values_list("instrument", "date", "price")
        ):
            days, values = self.prices[instrument]
            days.append(day)
            values.append(price)

    def market_value(
        self, account: int, opened: date, balance: Decimal, when: date
    ) -> Decimal:
        """The account's Market Value at the end of when, given its Balance then."""
        return self.position(account, opened, balance, when)[0]

    def position(
        self, account: int, opened: date, balance: Decimal, when: date
    ) -> tuple[Decimal, Decimal]:
        """The account's Market Value and Cost Basis at the end of when."""
        book = replay(self.events[account], until=when)
        value = market_value(
            cash(balance, book, opened), book, self._prices(book, when)
        )
        return value, book.cost_basis

    def _prices(self, book: Book, when: date) -> dict[int, Decimal]:
        found = {}
        for instrument in book.holdings:
            days, values = self.prices[instrument]
            at = bisect_right(days, when)
            if at:
                found[instrument] = values[at - 1]
        return found
