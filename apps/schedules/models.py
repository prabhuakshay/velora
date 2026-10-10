"""Schedules: Transactions the user expects to repeat, and their Occurrences."""

from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import Account
from apps.classification.models import Party

if TYPE_CHECKING:
    from collections.abc import Callable


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
    # The first due date, which every later one is counted from.
    start_date = models.DateField()
    # The repeat rule is an interval (every and unit) or a cron expression.
    every = models.PositiveSmallIntegerField(
        default=1, null=True, blank=True, validators=[MinValueValidator(1)]
    )
    unit = models.CharField(max_length=8, choices=Unit, default=Unit.MONTH, blank=True)
    cron = models.CharField(max_length=100, blank=True)
    # The last day it can fall due; open-ended when blank.
    ends_on = models.DateField(null=True, blank=True)
    # How many due dates it has at most, counted from the start date.
    ends_after = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)]
    )
    # Post the Transaction on the due date instead of proposing a Draft.
    auto_post = models.BooleanField(default=False)
    grace_days = models.PositiveSmallIntegerField(default=3)
    reminder_days = models.PositiveSmallIntegerField(default=3)
    active = models.BooleanField(default=True)
    # Due dates before this were paused, so they never fall due.
    resumed_on = models.DateField(null=True, blank=True, editable=False)

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
        ]

    def __str__(self) -> str:
        return self.description or str(self.party or f"Schedule {self.pk}")

    @property
    def amount(self) -> Decimal | None:
        """What it moves each time, or None while any Split's amount is open."""
        amounts = [split.amount for split in self.splits.all()]
        known = [amount for amount in amounts if amount is not None]
        if not amounts or len(known) < len(amounts):
            return None
        return sum(known, Decimal(0))


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

    class Meta:
        ordering = ("due_date", "pk")
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("schedule", "due_date"),
                name="schedules_occurrence_one_per_due_date",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.schedule} due {self.due_date}"

    def settle(self, *, paid: bool) -> None:
        """Mark it Paid, or Skipped when the user dropped its Draft."""
        self.status = Occurrence.Status.PAID if paid else Occurrence.Status.SKIPPED
        self.save(update_fields=["status"])
