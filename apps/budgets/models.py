"""Budgets: the most the user plans to spend in a calendar month (ADR 0008).

Each change is a row starting at the first day of the month it was made in, so
earlier months keep the Budget they had. The amount that applies in a month is
the newest row starting on or before it; a row with no amount means the Budget
was removed from that month on.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import Account, AccountKind
from apps.core.dates import month_start

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date


class Budget(models.Model):
    """One change to a Budget, from the start of a month until the next change.

    With no Account it is the Overall Budget.
    """

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="budgets",
        limit_choices_to={"kind": AccountKind.EXPENSE},
    )
    month = models.DateField(help_text="The first day of the month it starts from.")
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal(0))],
    )

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("account", "month"),
                nulls_distinct=False,
                name="budgets_budget_one_per_account_per_month",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0) | models.Q(amount__isnull=True),
                name="budgets_budget_amount_not_negative",
                violation_error_message="Enter 0 or more.",
            ),
            models.CheckConstraint(
                condition=models.Q(month__day=1),
                name="budgets_budget_month_starts_on_the_first",
            ),
        ]

    def __str__(self) -> str:
        name = self.account or "Overall Budget"
        return f"{name} from {self.month:%b %Y}"

    def clean(self) -> None:
        """Refuse a Budget on anything but an Expense Account."""
        if self.account and self.account.kind != AccountKind.EXPENSE:
            raise ValidationError({"account": "Choose an Expense Account."})


def set_budget(account: Account | None, amount: Decimal | None, today: date) -> None:
    """Set, change or, with no amount, remove a Budget from today's month on.

    With no Account it is the Overall Budget.
    """
    Budget.objects.update_or_create(
        account=account, month=month_start(today), defaults={"amount": amount}
    )


class BudgetWarning(models.Model):
    """A digest warning that a Budget became close or went over in a month.

    Its existence keeps the same warning from being sent again that month.
    With no Account it is about the Overall Budget.
    """

    class Level(models.TextChoices):
        CLOSE = "close"
        OVER = "over"

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="budget_warnings",
    )
    month = models.DateField(help_text="The first day of the month it is about.")
    level = models.CharField(max_length=5, choices=Level)
    sent_on = models.DateField()

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("account", "month", "level"),
                nulls_distinct=False,
                name="budgets_budgetwarning_one_per_level_per_month",
            ),
        ]

    def __str__(self) -> str:
        name = self.account or "Overall Budget"
        return f"{name} {self.level} in {self.month:%b %Y}"
