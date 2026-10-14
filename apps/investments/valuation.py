"""What Investment Accounts are worth, from their Investment Events and Prices."""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from functools import cached_property
from typing import TYPE_CHECKING, cast

from django.utils import timezone

from apps.investments.models import InvestmentEvent, Price
from apps.investments.replay import CENT, Book, Holding, replay
from apps.investments.xirr import returns

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping
    from datetime import date

    from apps.accounts.models import Account
    from apps.investments.models import Instrument
    from apps.investments.xirr import Flow


HUNDRED = Decimal(100)


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


class Valuer:
    """Values Investment Accounts on any dates up to until, in two queries.

    Each date uses the Investment Events up to it and the latest Price on or
    before it. Prices load only once a value needs them; given no accounts,
    it makes no query at all.
    """

    def __init__(self, accounts: Collection[int], until: date | None = None) -> None:
        """Load the accounts' Investment Events up to until, by default today."""
        self.until = until or timezone.localdate()
        self.events: dict[int, list[InvestmentEvent]] = defaultdict(list)
        self.instruments: dict[int, Instrument] = {}
        if not accounts:
            return
        for event in InvestmentEvent.objects.filter(
            account__in=accounts, date__lte=self.until
        ).select_related("instrument", "new_instrument"):
            self.events[event.account_id].append(event)
            for instrument in (event.instrument, event.new_instrument):
                if instrument is not None:
                    self.instruments[instrument.pk] = instrument

    @cached_property
    def prices(self) -> dict[int, tuple[list[date], list[Price]]]:
        """Each Instrument's Prices up to until, oldest first, with their dates."""
        found: dict[int, tuple[list[date], list[Price]]] = defaultdict(lambda: ([], []))
        for price in (
            Price.objects.filter(instrument__in=self.instruments, date__lte=self.until)
            .only("instrument", "date", "price")
            .order_by("date")
        ):
            days, prices = found[price.instrument_id]
            days.append(price.date)
            prices.append(price)
        return found

    def value(
        self, account: Account, balance: Decimal, on: date | None = None
    ) -> AccountValue:
        """The account's Cash, Holdings and Market Value at the end of on.

        Given its Balance then; on is until by default, and Prices are Stale
        against on, or today when not given.
        """
        when = on or self.until
        book = replay(self.events[account.pk], until=when)
        prices = self._prices(book, when)
        stale_on = on or timezone.localdate()
        rows = [
            HoldingRow(
                instrument=self.instruments[pk],
                units=holding.units,
                cost_basis=holding.cost_basis,
                market_value=_holding_value(holding, prices.get(pk)),
                realized=holding.realized,
                dividends=holding.dividends,
                price=prices.get(pk),
                stale=pk in prices and prices[pk].is_stale(stale_on),
                flows=tuple(holding.flows),
            )
            for pk, holding in book.holdings.items()
        ]
        rows.sort(key=lambda row: row.instrument.name)
        # Asset Accounts always have one, by their check constraint.
        held = _cash(balance, book, cast("date", account.opening_balance_date))
        return AccountValue(
            cash=held, market_value=_market_value(held, book, prices), holdings=rows
        )

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
        value = _market_value(
            _cash(balance, book, opened), book, self._prices(book, when)
        )
        return value, book.cost_basis

    def cash(self, account: int, opened: date, balance: Decimal, on: date) -> Decimal:
        """The account's Cash at the end of on, given its Balance then."""
        return _cash(balance, replay(self.events[account], until=on), opened)

    def _prices(self, book: Book, when: date) -> dict[int, Price]:
        found = {}
        for instrument in book.holdings:
            days, prices = self.prices[instrument]
            at = bisect_right(days, when)
            if at:
                found[instrument] = prices[at - 1]
        return found


def _cash(balance: Decimal, book: Book, opened: date) -> Decimal:
    """An Investment Account's Cash (ADR 0015).

    Its Balance less the Cost Basis still held, plus the Realized Gain of
    Sells after its Opening Balance date; earlier events are already inside
    its Opening Balance.
    """
    return (balance - book.cost_basis + book.realized_after(opened)).quantize(CENT)


def _market_value(cash: Decimal, book: Book, prices: Mapping[int, Price]) -> Decimal:
    """Cash plus each Holding's units at its Price.

    A Holding with no Price yet counts at its Cost Basis.
    """
    return cash + sum(
        (
            _holding_value(h, prices.get(h.instrument_id))
            for h in book.holdings.values()
        ),
        Decimal(0),
    )


def _holding_value(holding: Holding, price: Price | None) -> Decimal:
    """The Holding's Market Value, its Cost Basis while it has no Price."""
    if price is None:
        return holding.cost_basis
    return (holding.units * price.price).quantize(CENT)
