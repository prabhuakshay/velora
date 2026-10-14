"""Instruments, their Prices, and the Investment Events that build Lots."""

import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from django.db import models
from simple_history.models import HistoricalRecords

from apps.investments import replay
from apps.investments.trade_price import trade_price

if TYPE_CHECKING:
    from collections.abc import Callable
    from decimal import Decimal

    from apps.transactions.models import Transaction

STALE_AFTER = datetime.timedelta(days=5)


class PriceSource(models.TextChoices):
    """Where an Instrument's Prices come from."""

    AMFI = "AMFI", "AMFI"
    NSE = "NSE", "NSE"
    MANUAL = "Manual", "Manual"


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

    @property
    def price_source(self) -> PriceSource:
        """Where its Prices come from: Manual if priced by hand, else AMFI or NSE."""
        if self.manual_price:
            return PriceSource.MANUAL
        if self.kind == self.Kind.MUTUAL_FUND:
            return PriceSource.AMFI
        return PriceSource.NSE

    def latest_price(self) -> Price | None:
        """The newest Price, used until a newer one arrives."""
        return self.prices.order_by("-date").first()


class Price(models.Model):
    """What one unit of an Instrument was worth at the end of a day.

    It keeps its source itself, so removing old Price Fetches never loses it.
    """

    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="prices"
    )
    date = models.DateField()
    price = models.DecimalField(max_digits=16, decimal_places=4)
    source = models.CharField(max_length=8, choices=PriceSource)
    fetch = models.ForeignKey(
        "PriceFetch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prices",
    )

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

    def save(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Default the source to the Instrument's Price Source."""
        if not self.source:
            self.source = self.instrument.price_source
        super().save(*args, **kwargs)

    def is_stale(self, today: datetime.date) -> bool:
        """Whether the Price is more than five days older than today."""
        return today - self.date > STALE_AFTER


class PriceFetch(models.Model):
    """One time Velora fetched Prices from AMFI or NSE (see GLOSSARY.md).

    A nightly or Refresh one asks for one day and records the day its Prices
    are for, which for NSE can be an earlier file; a backfill asks for a range.
    """

    class Trigger(models.TextChoices):
        NIGHTLY = "nightly", "Nightly"
        REFRESH = "refresh", "Refresh"
        BACKFILL = "backfill", "Backfill"

    class Outcome(models.TextChoices):
        RUNNING = "running", "Running"
        OK = "ok", "Worked"
        FAILED = "failed", "Failed"

    source = models.CharField(
        max_length=8,
        choices=[(s.value, s.label) for s in (PriceSource.AMFI, PriceSource.NSE)],
    )
    trigger = models.CharField(max_length=8, choices=Trigger.choices)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(
        max_length=8, choices=Outcome.choices, default=Outcome.RUNNING
    )
    reason = models.CharField(max_length=500, blank=True)
    day_asked = models.DateField(null=True, blank=True)
    day_used = models.DateField(null=True, blank=True)
    range_start = models.DateField(null=True, blank=True)
    range_end = models.DateField(null=True, blank=True)
    prices_stored = models.PositiveIntegerField(default=0)
    instruments_priced = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("-started_at", "-pk")

    def __str__(self) -> str:
        return f"{self.source} {self.get_trigger_display()} at {self.started_at}"


class InvestmentEvent(models.Model):
    """One dated thing that happened to the units of an Instrument in an account.

    Lots are never stored: they come from replaying these (apps.investments.replay).
    Which fields a kind needs is in NEEDS, checked by its form and Drafts; units
    and amount stay optional here because a Dividend or Stock Split has no use
    for one of them. A Buy or Sell's Trade Price is derived, not stored (ADR 0016).
    A Stock Split keeps its ratio in units.
    """

    class Kind(models.TextChoices):
        BUY = replay.BUY, "Buy"
        SELL = replay.SELL, "Sell"
        DIVIDEND = replay.DIVIDEND, "Dividend"
        STOCK_SPLIT = replay.STOCK_SPLIT, "Stock Split"
        BONUS = replay.BONUS, "Bonus"
        MERGER = replay.MERGER, "Merger"

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        related_name="investment_events",
        limit_choices_to=~models.Q(investment_mode=""),
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.PROTECT, related_name="events"
    )
    # The Instrument a Merger turns the Lots into.
    new_instrument = models.ForeignKey(
        Instrument,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="merged_into_events",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    date = models.DateField()
    units = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    charges = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    note = models.CharField(max_length=200, blank=True)
    # The user's own reference from an Investment Import, for spotting duplicates.
    ref = models.CharField(max_length=100, blank=True)
    # The ledger Transaction that moved the event's money, such as a Dividend's.
    transaction = models.OneToOneField(
        "transactions.Transaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="investment_event",
    )

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        ordering = ("-date", "-pk")
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(kind__in=replay.TRADES)
                | models.Q(units__gt=0, amount__gt=0),
                name="investments_investmentevent_buy_sell_parts",
                violation_error_message=(
                    "A Buy or Sell needs units and an amount above 0."
                ),
            ),
            models.CheckConstraint(
                condition=~models.Q(kind=replay.DIVIDEND) | models.Q(amount__gt=0),
                name="investments_investmentevent_dividend_amount",
                violation_error_message="A Dividend needs an amount above 0.",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind__in=(replay.STOCK_SPLIT, replay.BONUS))
                | models.Q(units__gt=0),
                name="investments_investmentevent_units_given",
                violation_error_message=(
                    "A Stock Split needs a ratio, and a Bonus units, above 0."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(kind=replay.MERGER, new_instrument__isnull=False)
                | models.Q(~models.Q(kind=replay.MERGER), new_instrument__isnull=True),
                name="investments_investmentevent_new_instrument_iff_merger",
                violation_error_message=(
                    "Only a Merger, and every Merger, names a new Instrument."
                ),
            ),
            models.UniqueConstraint(
                fields=("ref",),
                condition=~models.Q(ref=""),
                name="investments_investmentevent_unique_ref",
                violation_error_message="Another Investment Event has this ref.",
            ),
            models.CheckConstraint(
                condition=models.Q(charges__gte=0),
                name="investments_investmentevent_charges_not_negative",
                violation_error_message="Charges can't be negative.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.instrument} on {self.date}"

    @property
    def trade_price(self) -> Decimal | None:
        """What one unit changed hands at; None for kinds without units and amount."""
        return trade_price(self.units, self.amount)


# What each kind of Investment Event needs; its other optional parts stay blank.
NEEDS: dict[str, tuple[str, ...]] = {
    InvestmentEvent.Kind.BUY: ("units", "amount"),
    InvestmentEvent.Kind.SELL: ("units", "amount"),
    InvestmentEvent.Kind.DIVIDEND: ("amount", "income_account"),
    InvestmentEvent.Kind.STOCK_SPLIT: ("units",),
    InvestmentEvent.Kind.BONUS: ("units",),
    InvestmentEvent.Kind.MERGER: ("new_isin",),
}


class DraftInvestment(models.Model):
    """The Buy, Sell or Dividend a Draft records when it is posted (ADR 0006).

    It builds no Lot and moves no Cash until then. Units may wait for a Price
    not yet published; posting is refused until units and amount are given.
    A Dividend's Income Account is the From of the Draft's Split, so merging
    Accounts repoints it like any Draft.
    """

    class Kind(models.TextChoices):
        BUY = replay.BUY, "Buy"
        SELL = replay.SELL, "Sell"
        DIVIDEND = replay.DIVIDEND, "Dividend"

    draft = models.OneToOneField(
        "quick_add.Draft", on_delete=models.CASCADE, related_name="investment"
    )
    # Deleting the Investment Account leaves the Draft with a gap, as for any
    # Draft Split, so posting it is refused.
    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        related_name="investment_drafts",
        limit_choices_to=~models.Q(investment_mode=""),
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.PROTECT, related_name="drafts"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    units = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    charges = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    # From an Investment Import row, passed on to the event when posted, so
    # importing the file again spots the row as recorded.
    ref = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=models.Q(charges__gte=0),
                name="investments_draftinvestment_charges_not_negative",
                violation_error_message="Charges can't be negative.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.instrument}"

    @property
    def trade_price(self) -> Decimal | None:
        """What one unit would change hands at; None while units or amount wait."""
        return trade_price(self.units, self.amount)

    def event_on(self, day: datetime.date) -> InvestmentEvent:
        """The Investment Event it becomes when posted on that day, unsaved."""
        return InvestmentEvent(
            account=self.account,
            instrument=self.instrument,
            kind=self.kind,
            date=day,
            units=self.units,
            amount=self.amount,
            charges=self.charges,
            ref=self.ref,
            note=self.note,
        )

    def record(self, transaction: Transaction) -> InvestmentEvent:
        """Save the Investment Event the posted Draft became, linked to its money."""
        event = self.event_on(transaction.date)
        event.transaction = transaction
        event.save()
        return event
