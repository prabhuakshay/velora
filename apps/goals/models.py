"""Goals and the Allocations that count what the user holds toward them (ADR 0014).

Goals are views only: nothing here moves money or changes a Balance.
"""

from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords

from apps.goals.progress import Share
from apps.goals.sources import source_key

if TYPE_CHECKING:
    from collections.abc import Callable

YEARLY_PERCENT = (MinValueValidator(0), MaxValueValidator(100))


class Goal(models.Model):
    """Something the user is saving for, by a date, in today's money.

    Inflation and expected return are yearly percentages; linked Schedules add
    to its Projection.
    """

    name = models.CharField(max_length=100)
    target_amount = models.DecimalField(max_digits=15, decimal_places=2)
    target_date = models.DateField()
    inflation = models.DecimalField(
        max_digits=5, decimal_places=2, default=6, validators=YEARLY_PERCENT
    )
    expected_return = models.DecimalField(
        max_digits=5, decimal_places=2, default=12, validators=YEARLY_PERCENT
    )
    schedules = models.ManyToManyField(
        "schedules.Schedule", blank=True, related_name="goals"
    )

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        ordering = ("target_date", Lower("name"))
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"),
                name="goals_goal_unique_name",
                violation_error_message="A Goal with this name already exists.",
            ),
            models.CheckConstraint(
                condition=models.Q(target_amount__gt=0),
                name="goals_goal_target_positive",
                violation_error_message="The target must be above 0.",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Allocation(models.Model):
    """A Goal's percentage or fixed amount of an Asset Account or one Holding.

    With an instrument it is the Holding of that Instrument in the account;
    without one it is the whole account.
    """

    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="allocations")
    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        related_name="goal_allocations",
        limit_choices_to={"kind": "asset"},
    )
    instrument = models.ForeignKey(
        "investments.Instrument",
        on_delete=models.CASCADE,
        related_name="goal_allocations",
        null=True,
        blank=True,
    )
    percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("goal", "account", "instrument"),
                nulls_distinct=False,
                name="goals_allocation_one_per_source",
                violation_error_message="This Goal already has that Allocation.",
            ),
            models.CheckConstraint(
                condition=models.Q(percent__isnull=True, amount__gt=0)
                | models.Q(amount__isnull=True, percent__gt=0, percent__lte=100),
                name="goals_allocation_percent_or_amount",
                violation_error_message=(
                    "Give a percentage above 0 and up to 100, or an amount above 0."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.goal}: {self.source_label}"

    @property
    def source_key(self) -> str:
        """The source as the Allocation form names it."""
        return source_key(self.account_id, self.instrument_id)

    @property
    def source_label(self) -> str:
        """The Account, or the Holding as Instrument in Account."""
        if self.instrument is None:
            return self.account.name
        return f"{self.instrument.name} in {self.account.name}"

    @property
    def share(self) -> Share:
        """The share as Goal Progress reads it."""
        return Share(percent=self.percent, amount=self.amount)
