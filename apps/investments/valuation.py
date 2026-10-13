"""What Investment Accounts are worth, from their Investment Events and Prices."""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.utils import timezone

from apps.investments.models import InvestmentEvent, Price
from apps.investments.replay import Book, cash, holding_value, market_value, replay
from apps.investments.xirr import returns

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from datetime import date

    from apps.accounts.models import Account
    from apps.investments.models import Instrument
    from apps.investments.xirr import Flow


HUNDRED = Decimal(100)


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
    dividends: Decimal
    price: Price | None
    stale: bool
    flows: tuple[Flow, ...] = ()

    @property
    def unrealized(self) -> Decimal:
        """Market Value less Cost Basis."""
        return self.market_value - self.cost_basis

    @property
    def xirr(self) -> Decimal | None:
        """XIRR of the Holding's Buys, Sells and Dividends and its value today."""
        return returns(self.flows, self.market_value, timezone.localdate())


@dataclass(frozen=True)
class Totals:
    """Cost Basis, Market Value and gains of some Holdings, plus any Cash."""

    cost_basis: Decimal
    holdings_value: Decimal
    realized: Decimal
    cash: Decimal = Decimal(0)
    flows: tuple[Flow, ...] = ()

    @classmethod
    def of(cls, rows: Iterable[HoldingRow], cash: Decimal = Decimal(0)) -> Totals:
        """The rows' figures added up, with the Cash beside them."""
        listed = list(rows)
        return cls(
            cost_basis=sum((row.cost_basis for row in listed), Decimal(0)),
            holdings_value=sum((row.market_value for row in listed), Decimal(0)),
            realized=sum((row.realized for row in listed), Decimal(0)),
            cash=cash,
            flows=tuple(flow for row in listed for flow in row.flows),
        )

    @property
    def market_value(self) -> Decimal:
        """The Holdings' Market Value plus Cash."""
        return self.holdings_value + self.cash

    @property
    def unrealized(self) -> Decimal:
        """The Holdings' Market Value less their Cost Basis; Cash has no gain."""
        return self.holdings_value - self.cost_basis

    @property
    def unrealized_percent(self) -> Decimal | None:
        """Unrealized Gain as a percentage of Cost Basis; None with no Cost Basis."""
        if not self.cost_basis:
            return None
        return self.unrealized / self.cost_basis * HUNDRED

    @property
    def xirr(self) -> Decimal | None:
        """XIRR of the Holdings' flows and their value today; Cash moves no return."""
        return returns(self.flows, self.holdings_value, timezone.localdate())


@dataclass(frozen=True)
class AccountValue:
    """An Investment Account's Cash, Holdings and Market Value now."""

    cash: Decimal
    market_value: Decimal
    holdings: list[HoldingRow]

    @property
    def totals(self) -> Totals:
        """Its Holdings added up, with its Cash beside them."""
        return Totals.of(self.holdings, self.cash)

    @property
    def cost_basis(self) -> Decimal:
        """The Cost Basis of every Holding together."""
        return self.totals.cost_basis

    @property
    def realized(self) -> Decimal:
        """The Realized Gain of every Sell, whatever its date."""
        return self.totals.realized

    @property
    def unrealized(self) -> Decimal:
        """Market Value of the Holdings less their Cost Basis."""
        return self.totals.unrealized

    @property
    def xirr(self) -> Decimal | None:
        """XIRR of every Holding together; Cash moves no return."""
        return self.totals.xirr


def account_value(account: Account, balance: Decimal) -> AccountValue:
    """Value the Investment Account at its latest Prices, given its Balance now."""
    events = list(
        account.investment_events.select_related("instrument", "new_instrument")
    )
    book = replay(events)
    instruments = {event.instrument_id: event.instrument for event in events} | {
        event.new_instrument_id: event.new_instrument
        for event in events
        if event.new_instrument is not None
    }
    prices = latest_prices(book.holdings)
    today = timezone.localdate()
    rows = [
        HoldingRow(
            instrument=instruments[pk],
            units=holding.units,
            cost_basis=holding.cost_basis,
            market_value=holding_value(holding, _value(prices.get(pk))),
            realized=holding.realized,
            dividends=holding.dividends,
            price=prices.get(pk),
            stale=pk in prices and prices[pk].is_stale(today),
            flows=tuple(holding.flows),
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
        instruments = {
            pk
            for es in self.events.values()
            for e in es
            for pk in (e.instrument_id, e.new_instrument_id)
            if pk is not None
        }
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
