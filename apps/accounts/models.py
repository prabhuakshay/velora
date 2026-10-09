"""Accounts: anything money moves from or to."""

from typing import TYPE_CHECKING, ClassVar, Self

from django.apps import apps
from django.db import models
from django.db.models.functions import Coalesce, Lower
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date
    from decimal import Decimal


class AccountKind(models.TextChoices):
    """What an Account is: Asset, Liability, Expense or Income."""

    ASSET = "asset"
    LIABILITY = "liability"
    EXPENSE = "expense"
    INCOME = "income"


BALANCE_KINDS = (AccountKind.ASSET, AccountKind.LIABILITY)


def _split_total(account_field: str, as_of: date | None) -> Coalesce:
    # Looked up by name: the transactions app imports this module.
    split = apps.get_model("transactions", "Split")
    splits = split.objects.filter(**{account_field: models.OuterRef("pk")})
    if as_of is not None:
        splits = splits.filter(transaction__date__lte=as_of)
    totals = (
        splits.values(account_field)
        .annotate(total=models.Sum("amount"))
        .values("total")
    )
    money = models.DecimalField(max_digits=15, decimal_places=2)
    return Coalesce(models.Subquery(totals), models.Value(0), output_field=money)


class AccountQuerySet(models.QuerySet["Account"]):
    """Queries over Accounts."""

    def with_balance(self, as_of: date | None = None) -> Self:
        """Annotate each Account's Balance; a Liability's reads as what is owed.

        With as_of, only Splits dated on or before it count, and an Account
        opening after it counts as 0.
        """
        moved_in = _split_total("to_account", as_of) - _split_total(
            "from_account", as_of
        )
        signed = models.Case(
            models.When(kind=AccountKind.LIABILITY, then=-moved_in),
            default=moved_in,
        )
        balance: models.Expression = models.F("opening_balance") + signed
        if as_of is not None:
            balance = models.Case(
                models.When(opening_balance_date__gt=as_of, then=models.Value(0)),
                default=balance,
                output_field=models.DecimalField(max_digits=15, decimal_places=2),
            )
        return self.annotate(balance=balance)


class Account(models.Model):
    """An Asset, Liability, Expense or Income Account; its kind never changes.

    Only Asset and Liability Accounts carry an Opening Balance and its date.
    """

    # Module-level so Meta's constraints can use BALANCE_KINDS built from it.
    Kind = AccountKind

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=Kind)
    notes = models.TextField(blank=True)
    hidden = models.BooleanField(default=False)
    include_in_net_worth = models.BooleanField("Include in Net Worth", default=True)
    opening_balance = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    opening_balance_date = models.DateField(null=True, blank=True)

    objects = AccountQuerySet.as_manager()
    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]
    # Set only on Accounts fetched through with_balance().
    balance: Decimal

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

    def opens_after(self, when: date) -> bool:
        """Whether the date falls before this Account's Opening Balance date."""
        started = self.opening_balance_date
        return started is not None and when < started
