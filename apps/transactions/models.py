"""Transactions: real-world money events made of Splits."""

from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import Account
from apps.classification.models import Party, Tag

if TYPE_CHECKING:
    from collections.abc import Callable


class Transaction(models.Model):
    """One real-world money event, with a date and optionally a Party."""

    date = models.DateField()
    party = models.ForeignKey(
        Party,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
    )
    description = models.TextField(blank=True)

    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]

    def __str__(self) -> str:
        return f"{self.date} {self.description or self.party or ''}".strip()


class Split(models.Model):
    """A positive amount moving from one Account to another (ADR 0003)."""

    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="splits"
    )
    from_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="splits_out"
    )
    to_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="splits_in"
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="splits")

    history = HistoricalRecords(m2m_fields=[tags])
    save_without_historical_record: Callable[..., None]

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="transactions_split_amount_positive",
                violation_error_message="Amount must be greater than zero.",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_account=models.F("to_account")),
                name="transactions_split_accounts_differ",
                violation_error_message="A Split cannot go from an Account to itself.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_account} to {self.to_account}: {self.amount}"
