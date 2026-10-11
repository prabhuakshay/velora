"""Laying out a Card EMI's installments, for its page and the form previews."""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from apps.cards.models import CardEMI, Installment


@dataclass(frozen=True)
class Row:
    """One installment and where it stands."""

    number: int
    closing: date
    installment: Installment
    # billed, next, upcoming, or cancelled once a foreclosure stops it.
    state: str


@dataclass(frozen=True)
class Foreclosure:
    """The rest of the principal and the fee, billed at once."""

    closing: date
    remaining: Decimal
    fee: Decimal
    saved: Decimal

    @property
    def billed(self) -> Decimal:
        """What it adds to the Statement Amount."""
        return self.remaining + self.fee

    @property
    def net(self) -> Decimal:
        """The interest and GST not paid, less the fee for not paying it."""
        return self.saved - self.fee


@dataclass(frozen=True)
class Plan:
    """A Card EMI's installments, as billed or as they would be."""

    emi: CardEMI
    rows: list[Row]

    @classmethod
    def of(cls, emi: CardEMI, today: date | None = None) -> Plan:
        """Lay out every installment; with no today, none is billed yet."""
        count = emi.billed_count
        rows = []
        upcoming = False
        for index, installment in enumerate(emi.installments()):
            closing = emi.closing(index)
            if index >= count:
                state = "cancelled"
            elif today is not None and closing <= today:
                state = "billed"
            else:
                state = "upcoming" if upcoming else "next"
                upcoming = True
            rows.append(Row(index + 1, closing, installment, state))
        return cls(emi, rows)

    @property
    def kept(self) -> list[Row]:
        """The installments a foreclosure leaves billed."""
        return [row for row in self.rows if row.state != "cancelled"]

    @property
    def monthly(self) -> Decimal:
        """The EMI itself: principal and interest, the same every month."""
        first = self.rows[0].installment
        return first.principal + first.interest

    @property
    def interest(self) -> Decimal:
        """Interest and the GST on it, over the installments billed."""
        return sum(
            (row.installment.charges for row in self.kept),
            Decimal(0),
        )

    @property
    def fees(self) -> Decimal:
        """The processing fee, and any foreclosure fee."""
        foreclosure = self.foreclosure
        return self.emi.processing_fee + (foreclosure.fee if foreclosure else 0)

    @property
    def cost(self) -> Decimal:
        """What it costs over paying the principal outright."""
        return self.interest + self.fees

    @property
    def total(self) -> Decimal:
        """The principal and what it costs."""
        return self.emi.principal + self.cost

    @property
    def next(self) -> Row | None:
        """The installment billed next, if any is left."""
        return next((row for row in self.rows if row.state == "next"), None)

    @property
    def billed(self) -> int:
        """How many installments are billed by today."""
        return sum(1 for row in self.rows if row.state == "billed")

    @property
    def foreclosure(self) -> Foreclosure | None:
        """What a foreclosure bills and saves, unless none stops an installment."""
        index = self.emi.foreclosure_index
        if index is None or index >= self.emi.months:
            return None
        cancelled = [row for row in self.rows if row.state == "cancelled"]
        return Foreclosure(
            closing=self.emi.closing(index),
            remaining=sum((row.installment.principal for row in cancelled), Decimal(0)),
            fee=self.emi.foreclosure_fee or Decimal(0),
            saved=sum(
                (row.installment.charges for row in cancelled),
                Decimal(0),
            ),
        )

    @property
    def ends(self) -> date:
        """The Statement Day of the last bill, a foreclosure's or the last one's."""
        if self.foreclosure:
            return self.foreclosure.closing
        return self.rows[-1].closing
