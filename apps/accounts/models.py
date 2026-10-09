"""Accounts: anything money moves from or to."""

from typing import TYPE_CHECKING, ClassVar

from django.db import models
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from collections.abc import Callable


BALANCE_KINDS = ("asset", "liability")


class Account(models.Model):
    """An Asset, Liability, Expense or Income Account; its kind never changes.

    Only Asset and Liability Accounts carry an Opening Balance and its date.
    """

    class Kind(models.TextChoices):
        ASSET = "asset"
        LIABILITY = "liability"
        EXPENSE = "expense"
        INCOME = "income"

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=Kind)
    notes = models.TextField(blank=True)
    hidden = models.BooleanField(default=False)
    opening_balance = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    opening_balance_date = models.DateField(null=True, blank=True)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), "kind", name="accounts_account_name_kind_ci_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=BALANCE_KINDS,
                    opening_balance__isnull=False,
                    opening_balance_date__isnull=False,
                )
                | (
                    ~models.Q(kind__in=BALANCE_KINDS)
                    & models.Q(
                        opening_balance__isnull=True,
                        opening_balance_date__isnull=True,
                    )
                ),
                name="accounts_account_opening_balance_by_kind",
                violation_error_message=(
                    "Only Asset and Liability Accounts have an Opening Balance "
                    "and date, and they need both."
                ),
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def has_opening_balance(self) -> bool:
        """Whether this kind of Account carries an Opening Balance."""
        return self.kind in BALANCE_KINDS
