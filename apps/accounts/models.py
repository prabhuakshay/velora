"""Accounts: anything money moves from or to."""

from typing import TYPE_CHECKING, ClassVar, Self

from django.apps import apps
from django.core.validators import MaxValueValidator, MinValueValidator
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
# Clamped to the last day of shorter months.
DAY_OF_MONTH = [MinValueValidator(1), MaxValueValidator(31)]


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
                output_field=self.model._meta.get_field("opening_balance"),
            )
        return self.annotate(balance=balance)


CARD_SETTINGS_TOGETHER = (
    "Set the Statement Day, Due Day and Pays from Account together, "
    "or leave all three blank."
)


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
    # Credit card settings, on Liability Accounts only: all three or none.
    statement_day = models.PositiveSmallIntegerField(
        "Statement Day",
        null=True,
        blank=True,
        validators=DAY_OF_MONTH,
        help_text="The day of the month the card's billing period closes.",
    )
    due_day = models.PositiveSmallIntegerField(
        "Due Day",
        null=True,
        blank=True,
        validators=DAY_OF_MONTH,
        help_text="The day of the month the Statement Amount must be paid by.",
    )
    pays_from = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cards_paid",
        limit_choices_to={"kind": AccountKind.ASSET},
        verbose_name="Pays from",
    )
    low_balance_threshold = models.DecimalField(
        "Low-Balance Threshold",
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Warn when the Forecast expects the Balance to fall below this.",
    )

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
            models.CheckConstraint(
                condition=models.Q(
                    kind=AccountKind.LIABILITY,
                    statement_day__isnull=False,
                    due_day__isnull=False,
                    pays_from__isnull=False,
                )
                | models.Q(
                    statement_day__isnull=True,
                    due_day__isnull=True,
                    pays_from__isnull=True,
                ),
                name="accounts_account_card_settings_together",
                violation_error_message=CARD_SETTINGS_TOGETHER,
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def has_opening_balance(self) -> bool:
        """Whether this kind of Account carries an Opening Balance."""
        return self.kind in BALANCE_KINDS

    @property
    def is_card(self) -> bool:
        """Whether it has credit card settings."""
        return self.statement_day is not None

    def opens_after(self, when: date) -> bool:
        """Whether the date falls before this Account's Opening Balance date."""
        started = self.opening_balance_date
        return started is not None and when < started
