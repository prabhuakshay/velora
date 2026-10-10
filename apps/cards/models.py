"""Credit card Statements: one per card per billing period."""

from decimal import Decimal
from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models

from apps.accounts.models import Account
from apps.transactions.models import Transaction


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
