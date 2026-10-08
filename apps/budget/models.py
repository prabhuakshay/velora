from typing import TYPE_CHECKING, ClassVar

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from collections.abc import Callable


class CategoryGroup(models.Model):
    class Kind(models.TextChoices):
        INCOME = "INCOME", "Income"
        EXPENSE = "EXPENSE", "Expense"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=7, choices=Kind)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), "owner", name="budget_group_owner_name_ci_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name
