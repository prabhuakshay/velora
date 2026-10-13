"""Schedules: Transactions the user expects to repeat, and their Occurrences."""

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import BALANCE_KINDS, Account, AccountKind
from apps.classification.models import Party
from apps.transactions.models import Transaction
from apps.transactions.split_rules import known_total

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date


class Schedule(models.Model):
    """A Transaction template with a repeat rule, proposing a Draft when due."""

    class Unit(models.TextChoices):
        DAY = "day"
        WEEK = "week"
        MONTH = "month"
        YEAR = "year"

    party = models.ForeignKey(
        Party,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="schedules",
    )
    description = models.TextField(blank=True)
    start_date = models.DateField()
    every = models.PositiveSmallIntegerField(
        default=1, null=True, blank=True, validators=[MinValueValidator(1)]
    )
    unit = models.CharField(max_length=8, choices=Unit, default=Unit.MONTH, blank=True)
    cron = models.CharField(max_length=100, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    ends_after = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)]
    )
    auto_post = models.BooleanField(default=False)
    grace_days = models.PositiveSmallIntegerField(default=3)
    reminder_days = models.PositiveSmallIntegerField(default=3)
    active = models.BooleanField(default=True)
    # Due dates before this were paused, so they never fall due.
    resumed_on = models.DateField(null=True, blank=True, editable=False)
    # A Subscription is a flagged Schedule, not a model of its own (ADR 0007).
    is_subscription = models.BooleanField(default=False)
    trial_ends_on = models.DateField(null=True, blank=True)
    plan = models.CharField(max_length=100, blank=True)
    how_to_cancel = models.TextField(blank=True)
    # A SIP is a flagged Schedule too: it buys one Instrument in a Direct
    # Investment Account on each due date.
    sip_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sips",
        limit_choices_to={"investment_mode": Account.InvestmentMode.DIRECT},
    )
    sip_instrument = models.ForeignKey(
        "investments.Instrument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sips",
    )

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        ordering = ("pk",)
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=(models.Q(cron="", every__isnull=False) & ~models.Q(unit=""))
                | (~models.Q(cron="") & models.Q(every__isnull=True, unit="")),
                name="schedules_schedule_interval_or_cron",
                violation_error_message=(
                    "A Schedule repeats on an interval or a cron expression, not both."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(
                    sip_account__isnull=True,
                    sip_instrument__isnull=True,
                )
                | models.Q(sip_account__isnull=False, sip_instrument__isnull=False),
                name="schedules_schedule_sip_account_and_instrument",
                violation_error_message=(
                    "A SIP needs both an Instrument and an Investment Account."
                ),
            ),
        ]

    def __str__(self) -> str:
        return self.description or str(self.party or f"Schedule {self.pk}")

    @property
    def amount(self) -> Decimal | None:
        """What it moves each time, or None while any Split's amount is open."""
        return known_total(split.amount for split in self.splits.all())

    @property
    def is_income(self) -> bool:
        """Whether any Split comes from an Income Account."""
        return any(
            split.from_account.kind == AccountKind.INCOME for split in self.splits.all()
        )

    @property
    def is_transfer(self) -> bool:
        """Whether every Split moves money between Asset and Liability Accounts."""
        return all(
            split.from_account.kind in BALANCE_KINDS
            and split.to_account.kind in BALANCE_KINDS
            for split in self.splits.all()
        )

    @property
    def is_sip(self) -> bool:
        """Whether it buys an Instrument on each due date."""
        return self.sip_account_id is not None

    def has_ended(self, today: date) -> bool:
        """Whether it was ended before today."""
        return self.ends_on is not None and self.ends_on < today


class ScheduleSplit(models.Model):
    """One Split of a Schedule's template; a blank amount changes every time."""

    schedule = models.ForeignKey(
        Schedule, on_delete=models.CASCADE, related_name="splits"
    )
    from_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="schedule_splits_out"
    )
    to_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="schedule_splits_in"
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        ordering = ("pk",)

    def __str__(self) -> str:
        return f"{self.from_account} to {self.to_account}: {self.amount or '?'}"


class Occurrence(models.Model):
    """One due date of a Schedule, and what became of it."""

    class Status(models.TextChoices):
        UPCOMING = "upcoming"
        DRAFTED = "drafted"
        PAID = "paid"
        SKIPPED = "skipped"
        MISSED = "missed"

    schedule = models.ForeignKey(
        Schedule, on_delete=models.CASCADE, related_name="occurrences"
    )
    due_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status, default=Status.UPCOMING)
    # One-to-one so a Transaction covers at most one Occurrence.
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="occurrence",
    )

    class Meta:
        ordering = ("due_date", "pk")
        indexes: ClassVar = [models.Index(fields=["status", "due_date"])]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("schedule", "due_date"),
                name="schedules_occurrence_one_per_due_date",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.schedule} due {self.due_date}"

    def auto_posts_on(self, today: date) -> bool:
        """Whether its Draft is posted for the user: auto-post, within grace."""
        schedule = self.schedule
        return (
            schedule.auto_post
            and schedule.amount is not None
            and self.due_date + timedelta(days=schedule.grace_days) >= today
        )

    def settle(self, transaction: Transaction | None) -> None:
        """Mark it Paid by the Transaction, or Skipped when there is none."""
        self.transaction = transaction
        self.status = (
            Occurrence.Status.PAID if transaction else Occurrence.Status.SKIPPED
        )
        self.save(update_fields=["transaction", "status"])


class SuggestedSchedule(models.Model):
    """A steady repeated payment Velora noticed, offered as a Schedule.

    It does nothing until confirmed. Dismissed ones are kept so detection
    never offers the same Party, Accounts and interval again.
    """

    class Status(models.TextChoices):
        WAITING = "waiting"
        CONFIRMED = "confirmed"
        DISMISSED = "dismissed"

    # Cascades so a suggestion never blocks merging or deleting its Party.
    party = models.ForeignKey(
        Party, on_delete=models.CASCADE, related_name="suggested_schedules"
    )
    from_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="suggested_schedules_out"
    )
    to_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="suggested_schedules_in"
    )
    # The median of the evidence.
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    unit = models.CharField(max_length=8, choices=Schedule.Unit)
    evidence = models.ManyToManyField(
        "transactions.Transaction", related_name="suggested_schedules"
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.WAITING)

    class Meta:
        ordering = ("pk",)
        indexes: ClassVar = [models.Index(fields=["status"])]

    def __str__(self) -> str:
        return f"{self.party} every {self.unit}"
