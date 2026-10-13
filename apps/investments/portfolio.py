"""The whole portfolio: every Holding across Investment Accounts, and their totals."""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models.functions import Lower

from apps.accounts.models import Account
from apps.investments.models import Instrument
from apps.investments.valuation import Totals, account_value

if TYPE_CHECKING:
    from collections.abc import Callable

    from apps.investments.valuation import AccountValue, HoldingRow

# Holdings with no XIRR sort below every one that has one.
NO_XIRR = Decimal("-Infinity")
KIND_TITLES = {
    Instrument.Kind.MUTUAL_FUND: "Mutual funds",
    Instrument.Kind.STOCK: "Stocks",
    Instrument.Kind.ETF: "ETFs",
}


@dataclass(frozen=True)
class Held:
    """One open Holding on the Holdings table, with the account it is in."""

    account: Account
    row: HoldingRow

    @property
    def average_cost(self) -> Decimal:
        """Cost Basis per unit held."""
        return self.row.cost_basis / self.row.units

    @property
    def unrealized_percent(self) -> Decimal | None:
        """Unrealized Gain as a percentage of Cost Basis."""
        return Totals.of([self.row]).unrealized_percent


@dataclass(frozen=True)
class Column:
    """A Holdings table column: its ?sort= key, heading and what it sorts by."""

    key: str
    title: str
    sort_by: Callable[[Held], Decimal | str]
    numeric: bool = True


COLUMNS = (
    Column(
        "instrument",
        "Instrument",
        lambda h: h.row.instrument.name.lower(),
        numeric=False,
    ),
    Column(
        "account",
        "Investment Account",
        lambda h: h.account.name.lower(),
        numeric=False,
    ),
    Column("units", "Units", lambda h: h.row.units),
    Column("average_cost", "Average cost", lambda h: h.average_cost),
    Column("invested", "Invested", lambda h: h.row.cost_basis),
    Column("market_value", "Market Value", lambda h: h.row.market_value),
    Column("gain", "Gain", lambda h: h.row.unrealized),
    Column("xirr", "XIRR", lambda h: NO_XIRR if (x := h.row.xirr) is None else x),
)


def sorting(sort: str) -> tuple[Column, bool]:
    """The column ?sort= names and whether it runs high to low.

    A leading "-" sorts high to low; anything unknown sorts by Instrument.
    """
    key = sort.removeprefix("-")
    for column in COLUMNS:
        if column.key == key:
            return column, sort.startswith("-")
    return COLUMNS[0], False


@dataclass(frozen=True)
class Portfolio:
    """Each Investment Account's value and every Holding across them."""

    accounts: list[tuple[Account, AccountValue]]

    @property
    def rows(self) -> list[HoldingRow]:
        """Every Holding of every account, including ones sold off."""
        return [row for _, value in self.accounts for row in value.holdings]

    @property
    def totals(self) -> Totals:
        """Every Holding added up, including the Realized Gain of ones sold off.

        Its Market Value includes every account's Cash, as Net Worth counts it.
        """
        cash = sum((value.cash for _, value in self.accounts), Decimal(0))
        return Totals.of(self.rows, cash)

    def holdings(self, column: Column, *, descending: bool) -> list[Held]:
        """The Holdings still held, by the column; ties by Instrument A to Z."""
        held = sorted(
            (
                Held(account, row)
                for account, value in self.accounts
                for row in value.holdings
                if row.units
            ),
            key=COLUMNS[0].sort_by,
        )
        return sorted(held, key=column.sort_by, reverse=descending)

    def by_kind(self) -> list[tuple[str, Totals]]:
        """The totals of each kind of Instrument held, in KIND_TITLES order."""
        rows = self.rows
        return [
            (title, Totals.of(row for row in rows if row.instrument.kind == kind))
            for kind, title in KIND_TITLES.items()
            if any(row.instrument.kind == kind for row in rows)
        ]


def portfolio() -> Portfolio:
    """Value every Investment Account at its latest Prices."""
    accounts = Account.objects.exclude(investment_mode="").with_balance()
    return Portfolio(
        accounts=[
            (account, account_value(account, account.balance))
            for account in accounts.order_by(Lower("name"))
        ]
    )
