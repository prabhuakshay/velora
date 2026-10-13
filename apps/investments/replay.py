"""Lots worked out by replaying Investment Events in date order (ADR 0012).

Nothing here touches the database: callers pass events in, and the same
events always give the same Lots, so a past event edited or deleted never
leaves Lots stale.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from datetime import date

    from apps.investments.xirr import Flow

BUY = "buy"
BONUS = "bonus"
STOCK_SPLIT = "stock_split"
MERGER = "merger"
DIVIDEND = "dividend"
SELL = "sell"
CENT = Decimal("0.01")
# Events on one day apply in this order, so a same-day Sell can take what
# that day's Buy or Bonus added.
DAY_ORDER = (BUY, BONUS, STOCK_SPLIT, MERGER, DIVIDEND, SELL)


class Event(Protocol):
    """What replay reads from an Investment Event."""

    @property
    def kind(self) -> str: ...  # noqa: D102

    @property
    def date(self) -> date: ...  # noqa: D102

    @property
    def instrument_id(self) -> int: ...  # noqa: D102

    @property
    def new_instrument_id(self) -> int | None: ...  # noqa: D102

    @property
    def units(self) -> Decimal | None: ...  # noqa: D102

    @property
    def amount(self) -> Decimal | None: ...  # noqa: D102

    @property
    def charges(self) -> Decimal: ...  # noqa: D102


class OversoldError(Exception):
    """A Sell took more units than were held on its date."""

    def __init__(self, event: Event, held: Decimal) -> None:
        """Keep the Sell and the units held when it came."""
        super().__init__(f"Sold {event.units} units on {event.date}, held {held}.")
        self.event = event
        self.held = held


@dataclass
class Lot:
    """Units got together in one Buy or Bonus, with what they cost."""

    date: date
    units: Decimal
    cost: Decimal


@dataclass
class Holding:
    """All the units of one Instrument: its open Lots, oldest first."""

    instrument_id: int
    lots: list[Lot] = field(default_factory=list)
    # Realized Gain of every Sell, whatever its date.
    realized: Decimal = Decimal(0)
    dividends: Decimal = Decimal(0)
    # Money out to Buys (negative) and in from Sells and Dividends, for XIRR.
    flows: list[Flow] = field(default_factory=list)

    @property
    def units(self) -> Decimal:
        """The units held across open Lots."""
        return sum((lot.units for lot in self.lots), Decimal(0))

    @property
    def cost_basis(self) -> Decimal:
        """What the units still held cost, charges included."""
        return sum((lot.cost for lot in self.lots), Decimal(0))

    def take(self, units: Decimal) -> Decimal:
        """Remove units from the oldest Lots first; return the cost taken."""
        left, cost_out = units, Decimal(0)
        for lot in self.lots:
            took = min(lot.units, left)
            cost = lot.cost * took / lot.units
            lot.units -= took
            lot.cost -= cost
            cost_out += cost
            left -= took
            if not left:
                break
        self.lots = [lot for lot in self.lots if lot.units]
        return cost_out


@dataclass(frozen=True)
class Realization:
    """One Sell's Realized Gain: what it brought in less the cost it took."""

    date: date
    instrument_id: int
    gain: Decimal


@dataclass
class Book:
    """Every Holding after a replay, and the Realized Gain of each Sell."""

    holdings: dict[int, Holding] = field(default_factory=dict)
    realizations: list[Realization] = field(default_factory=list)

    @property
    def cost_basis(self) -> Decimal:
        """The Cost Basis of every Holding together."""
        return sum((h.cost_basis for h in self.holdings.values()), Decimal(0))

    def realized_after(self, day: date) -> Decimal:
        """The Realized Gain of Sells dated after the day."""
        return sum((r.gain for r in self.realizations if r.date > day), Decimal(0))

    def holding(self, instrument_id: int) -> Holding:
        """The Holding of the Instrument, empty if never held."""
        return self.holdings.setdefault(instrument_id, Holding(instrument_id))


def in_order[E: Event](events: Iterable[E]) -> list[E]:
    """The events in the order replay applies them: by date, then DAY_ORDER."""
    return sorted(events, key=lambda e: (e.date, DAY_ORDER.index(e.kind)))


def replay(events: Iterable[Event], until: date | None = None) -> Book:
    """Apply the events in order, those dated after until left out.

    Raises OversoldError when a Sell takes more than is held on its date.
    """
    book = Book()
    for event in in_order(events):
        if until is not None and event.date > until:
            break
        _apply(book, event)
    return book


def _apply(book: Book, event: Event) -> None:
    APPLY[event.kind](book, book.holding(event.instrument_id), event)


def _buy(_book: Book, holding: Holding, event: Event) -> None:
    cost = _amount(event) + event.charges
    holding.lots.append(Lot(event.date, _units(event), cost))
    holding.flows.append((event.date, -cost))


def _sell(book: Book, holding: Holding, event: Event) -> None:
    held, units = holding.units, _units(event)
    if units > held:
        raise OversoldError(event, held)
    proceeds = _amount(event) - event.charges
    gain = proceeds - holding.take(units)
    holding.flows.append((event.date, proceeds))
    holding.realized += gain
    book.realizations.append(Realization(event.date, event.instrument_id, gain))


def _bonus(_book: Book, holding: Holding, event: Event) -> None:
    holding.lots.append(Lot(event.date, _units(event), Decimal(0)))


def _stock_split(_book: Book, holding: Holding, event: Event) -> None:
    # A Stock Split keeps its ratio in units.
    for lot in holding.lots:
        lot.units *= _units(event)


def _merger(book: Book, holding: Holding, event: Event) -> None:
    # A Merger always names the Instrument it turns into.
    into = book.holding(cast("int", event.new_instrument_id))
    into.lots = sorted([*into.lots, *holding.lots], key=lambda lot: lot.date)
    holding.lots = []
    into.flows = sorted([*into.flows, *holding.flows])
    holding.flows = []


def _dividend(_book: Book, holding: Holding, event: Event) -> None:
    holding.dividends += _amount(event)
    holding.flows.append((event.date, _amount(event)))


def _units(event: Event) -> Decimal:
    return event.units or Decimal(0)


def _amount(event: Event) -> Decimal:
    return event.amount or Decimal(0)


APPLY: dict[str, Callable[[Book, Holding, Event], None]] = {
    BUY: _buy,
    SELL: _sell,
    BONUS: _bonus,
    STOCK_SPLIT: _stock_split,
    MERGER: _merger,
    DIVIDEND: _dividend,
}


def cash(balance: Decimal, book: Book, opened: date) -> Decimal:
    """An Investment Account's Cash (ADR 0015).

    Its Balance less the Cost Basis still held, plus the Realized Gain of
    Sells after its Opening Balance date; earlier events are already inside
    its Opening Balance.
    """
    return (balance - book.cost_basis + book.realized_after(opened)).quantize(CENT)


def market_value(
    cash_held: Decimal, book: Book, prices: Mapping[int, Decimal]
) -> Decimal:
    """Cash plus each Holding's units at its Price.

    A Holding with no Price yet counts at its Cost Basis.
    """
    return cash_held + sum(
        (holding_value(h, prices.get(h.instrument_id)) for h in book.holdings.values()),
        Decimal(0),
    )


def holding_value(holding: Holding, price: Decimal | None) -> Decimal:
    """The Holding's Market Value, its Cost Basis while it has no Price."""
    if price is None:
        return holding.cost_basis
    return (holding.units * price).quantize(CENT)
