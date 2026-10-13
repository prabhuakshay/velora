"""Reconciliations: what a bank or broker said an Account held on a day."""

from typing import TYPE_CHECKING, ClassVar, Self

from django.db import models

from apps.accounts.models import Account, reconciliation_difference

if TYPE_CHECKING:
    from decimal import Decimal


class ReconciliationQuerySet(models.QuerySet["Reconciliation"]):
    """Queries over Reconciliations."""

    def with_difference(self) -> Self:
        """Annotate its balance less the Account's Balance on its date now.

        Zero means it still matches; nothing about matching is stored (ADR 0011).
        """
        return self.annotate(difference=reconciliation_difference())

    def matching(self) -> Self:
        """Those whose balance still equals the Account's Balance on their date."""
        return self.with_difference().filter(difference=0)


class Reconciliation(models.Model):
    """The balance the bank said an Account held on a day, matched when recorded.

    Checked against the Balance whenever shown, never locked (ADR 0011). A
    Liability's balance reads as what is owed, like its Balance.
    """

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="reconciliations"
    )
    date = models.DateField()
    balance = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ReconciliationQuerySet.as_manager()
    # Set only on Reconciliations fetched through with_difference().
    difference: Decimal

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("account", "date"),
                name="accounts_reconciliation_account_date_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.account} on {self.date}"
