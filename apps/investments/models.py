"""Instruments, their Prices, and the Investment Events that build Lots."""

import datetime
from typing import TYPE_CHECKING, ClassVar

from django.db import models
from simple_history.models import HistoricalRecords

from apps.investments import replay

if TYPE_CHECKING:
    from collections.abc import Callable

STALE_AFTER = datetime.timedelta(days=5)


class Instrument(models.Model):
    """A mutual fund scheme, stock or ETF, identified by its ISIN.

    One with a manual Price is priced by hand; the nightly job leaves it alone.
    """

    class Kind(models.TextChoices):
        MUTUAL_FUND = "mutual_fund", "Mutual fund"
        STOCK = "stock", "Stock"
        ETF = "etf", "ETF"

    isin = models.CharField("ISIN", max_length=12, unique=True)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    manual_price = models.BooleanField(default=False)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def latest_price(self) -> Price | None:
        """The newest Price, used until a newer one arrives."""
        return self.prices.order_by("-date").first()


class Price(models.Model):
    """What one unit of an Instrument was worth at the end of a day."""

    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="prices"
    )
    date = models.DateField()
    price = models.DecimalField(max_digits=16, decimal_places=4)

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("instrument", "date"), name="one_price_per_instrument_per_day"
            ),
            models.CheckConstraint(
                condition=models.Q(price__gt=0), name="price_positive"
            ),
        )

    def __str__(self) -> str:
        return f"{self.instrument} on {self.date}"

    def is_stale(self, today: datetime.date) -> bool:
        """Whether the Price is more than five days older than today."""
        return today - self.date > STALE_AFTER


class InvestmentEvent(models.Model):
    """One dated thing that happened to the units of an Instrument in an account.

    Lots are never stored: they come from replaying these (apps.investments.replay).
    Which fields a kind needs is kept to its form and import; units, amount and
    price stay optional here because a Dividend or Stock Split has no use for some.
    """

    class Kind(models.TextChoices):
        BUY = replay.BUY, "Buy"
        SELL = replay.SELL, "Sell"

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        related_name="investment_events",
        limit_choices_to=~models.Q(investment_mode=""),
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.PROTECT, related_name="events"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    date = models.DateField()
    units = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    price = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    charges = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    note = models.CharField(max_length=200, blank=True)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        ordering = ("-date", "-pk")
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(kind__in=(replay.BUY, replay.SELL))
                | models.Q(units__gt=0, price__gt=0, amount__gt=0),
                name="investments_investmentevent_trade_parts",
                violation_error_message=(
                    "A Buy or Sell needs units, a Price and an amount above 0."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(charges__gte=0),
                name="investments_investmentevent_charges_not_negative",
                violation_error_message="Charges can't be negative.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.instrument} on {self.date}"
