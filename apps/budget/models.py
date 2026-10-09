"""Budget models: categories and expense accounts."""

from typing import TYPE_CHECKING, ClassVar

from django.db import models
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from collections.abc import Callable


# Full class names, so Tailwind finds them when scanning this file.
COLOR_CLASSES = {
    "slate": "text-slate-600",
    "red": "text-red-600",
    "orange": "text-orange-600",
    "amber": "text-amber-600",
    "green": "text-green-600",
    "cyan": "text-cyan-600",
    "blue": "text-blue-600",
    "violet": "text-violet-600",
    "pink": "text-pink-600",
}


SWATCH_CLASSES = {
    "slate": "bg-slate-600",
    "red": "bg-red-600",
    "orange": "bg-orange-600",
    "amber": "bg-amber-600",
    "green": "bg-green-600",
    "cyan": "bg-cyan-600",
    "blue": "bg-blue-600",
    "violet": "bg-violet-600",
    "pink": "bg-pink-600",
}


class Category(models.Model):
    """A budget category, either income or expense.

    Deferred until transactions land:
    - Deleting a category must first reassign its transactions.
    - A category's kind can't change once it has transactions.
    """

    class Kind(models.TextChoices):
        INCOME = "INCOME", "Income"
        EXPENSE = "EXPENSE", "Expense"

    kind = models.CharField(max_length=7, choices=Kind)
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=64, default="tag")
    description = models.CharField(max_length=500, blank=True)
    color = models.CharField(
        max_length=16, choices=[(name, name.title()) for name in COLOR_CLASSES]
    )
    hidden = models.BooleanField(default=False)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        verbose_name_plural = "categories"
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"),
                "kind",
                name="budget_category_kind_name_ci_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def color_class(self) -> str:
        """Tailwind text colour class for the category's colour."""
        return COLOR_CLASSES[self.color]


class ExpenseAccount(models.Model):
    """Where money goes when it is spent.

    Deferred until transactions land:
    - Transactions reference expense accounts with PROTECT.
    - Deleting an expense account is blocked while it has transactions; the
      user merges it instead.
    - Merging repoints the source's transactions to the target, atomically.
    """

    name = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    hidden = models.BooleanField(default=False)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        verbose_name_plural = "expense accounts"
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"),
                name="budget_expenseaccount_name_ci_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.name
