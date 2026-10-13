"""Instruments and their Prices."""

import datetime

from django.db import models

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
