"""Accounts: anything money moves from or to."""

from typing import TYPE_CHECKING, ClassVar

from django.db import models
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from collections.abc import Callable


class Account(models.Model):
    """An Asset, Liability, Expense or Income Account; its kind never changes."""

    class Kind(models.TextChoices):
        ASSET = "asset"
        LIABILITY = "liability"
        EXPENSE = "expense"
        INCOME = "income"

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=Kind)
    notes = models.TextField(blank=True)
    hidden = models.BooleanField(default=False)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), "kind", name="accounts_account_name_kind_ci_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name
