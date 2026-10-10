"""Credit card Statements, one per card per billing period, and Card EMIs."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MinValueValidator
from django.db import models

from apps.accounts.models import Account, AccountKind
from apps.core.dates import day_of
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    import datetime

GST_RATE = Decimal("0.18")
CENT = Decimal("0.01")


class Statement(models.Model):
    """A card's billing period and what it asks the user to pay."""

    card = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="statements"
    )
    period_start = models.DateField()
    # The Statement Day the period closed on.
    period_end = models.DateField()
    due_date = models.DateField()
    estimated_amount = models.DecimalField(max_digits=15, decimal_places=2)
    actual_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal(0))],
        help_text="From the real statement; leave blank to use the estimate.",
    )
    # The payment that settled it; one-to-one so it settles only this one.
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="statement",
    )

    class Meta:
        ordering = ("period_end", "pk")
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("card", "period_end"),
                name="cards_statement_one_per_period",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.card} Statement to {self.period_end}"

    @property
    def amount(self) -> Decimal:
        """The Statement Amount: the actual one once entered, else the estimate."""
        if self.actual_amount is not None:
            return self.actual_amount
        return self.estimated_amount


@dataclass(frozen=True)
class Installment:
    """One month of a Card EMI, as the bank bills it."""

    principal: Decimal
    interest: Decimal

    @property
    def gst(self) -> Decimal:
        """GST is charged on the interest only."""
        return (self.interest * GST_RATE).quantize(CENT, ROUND_HALF_UP)

    @property
    def billed(self) -> Decimal:
        """What it adds to the Statement Amount."""
        return self.principal + self.interest + self.gst


@dataclass(frozen=True)
class Progress:
    """How far through its installments a Card EMI is."""

    paid: int
    left: int
    end_month: datetime.date


class CardEMI(models.Model):
    """A card purchase the bank bills in monthly installments with interest."""

    # Recorded once at full price; only the installments reach each Statement.
    purchase = models.OneToOneField(
        Transaction, on_delete=models.CASCADE, related_name="card_emi"
    )
    card = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="card_emis"
    )
    principal = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(CENT)],
    )
    months = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    annual_rate = models.DecimalField(
        "Annual interest rate (%)",
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal(0))],
        help_text="0 for a no-cost EMI.",
    )
    processing_fee = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal(0),
        validators=[MinValueValidator(Decimal(0))],
    )
    # The Statement Day closing the period the first installment is billed in;
    # each later one is billed in the period closing a month after.
    first_statement = models.DateField("First billed Statement")
    interest_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="card_emi_interest",
        limit_choices_to={"kind": AccountKind.EXPENSE},
        verbose_name="Interest Expense Account",
    )
    foreclosed_on = models.DateField(null=True, blank=True)
    foreclosure_fee = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal(0))],
    )

    class Meta:
        ordering = ("first_statement", "pk")
        verbose_name = "Card EMI"

    def __str__(self) -> str:
        return f"{self.card} Card EMI of {self.principal}"

    def installments(self) -> list[Installment]:
        """Every installment, by the standard reducing-balance EMI formula."""
        rate = self.annual_rate / 1200
        if rate:
            growth = (1 + rate) ** self.months
            emi = self.principal * rate * growth / (growth - 1)
        else:
            emi = self.principal / self.months
        emi = emi.quantize(CENT, ROUND_HALF_UP)
        balance = self.principal
        schedule = []
        for number in range(1, self.months + 1):
            interest = (balance * rate).quantize(CENT, ROUND_HALF_UP)
            # The last one clears whatever rounding left over.
            principal = balance if number == self.months else emi - interest
            balance -= principal
            schedule.append(Installment(principal, interest))
        return schedule

    def closing(self, index: int) -> datetime.date:
        """The Statement Day closing the period of the installment at index."""
        day = self.card.statement_day or self.first_statement.day
        first = self.first_statement
        return day_of(first.year, first.month + index, day)

    def _index(self, on: datetime.date) -> int:
        """Which installment's period closes in the month of `on`."""
        first = self.first_statement
        return (on.year - first.year) * 12 + on.month - first.month

    @property
    def foreclosure_index(self) -> int | None:
        """The period the foreclosure is billed in: the next one to close."""
        if self.foreclosed_on is None:
            return None
        index = self._index(self.foreclosed_on)
        return index if self.closing(index) >= self.foreclosed_on else index + 1

    @property
    def billed_count(self) -> int:
        """How many installments are billed before any foreclosure stops them."""
        stop = self.foreclosure_index
        return self.months if stop is None else max(0, min(stop, self.months))

    def billed(self, start: datetime.date, end: datetime.date) -> Decimal:
        """How the EMI changes the estimate for the period from start to end.

        The purchase leaves the period it was made in, and the installment, or
        the foreclosure, joins the period it is billed in.
        """
        amount = Decimal(0)
        if start <= self.purchase.date <= end:
            amount -= self.principal
        index = self._index(end)
        if index == 0:
            amount += self.processing_fee
        schedule = self.installments()
        if 0 <= index < self.billed_count:
            amount += schedule[index].billed
        if index == self.foreclosure_index and index < self.months:
            paid_off = sum(item.principal for item in schedule[: self.billed_count])
            amount += self.principal - paid_off + (self.foreclosure_fee or 0)
        return amount

    def progress(self, today: datetime.date) -> Progress:
        """Installments billed by today, those still to come, and the last month."""
        count = self.billed_count
        paid = sum(1 for index in range(count) if self.closing(index) <= today)
        last = self.foreclosure_index
        last = self.months - 1 if last is None else min(last, self.months - 1)
        return Progress(paid, count - paid, self.closing(last))
